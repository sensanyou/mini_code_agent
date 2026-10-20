import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from task_system import TaskStore


AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Teammate:
    name: str
    role: str
    status: str
    task_id: str | None


class TeammateRuntime:
    def __init__(
        self,
        name: str,
        role: str,
        task_id: str | None,
        runner: Callable[[str, str], str],
        task_store: TaskStore | None,
    ):
        self.name = name
        self.role = role
        self.task_id = task_id
        self.runner = runner
        self.task_store = task_store
        self.inbox: queue.Queue[str | None] = queue.Queue()
        self.status = "idle"
        self.thread = threading.Thread(
            target=self._loop,
            name=f"teammate-{name}",
            daemon=True,
        )

    def _loop(self) -> None:
        while True:
            message = self.inbox.get()

            if message is None:
                self.status = "stopped"
                return

            claimed = False

            try:
                if self.task_id and self.task_store:
                    self.task_store.claim(self.task_id, self.name)
                    claimed = True

                self.status = "running"
                result = self.runner(message, self.role)
                completion = ""

                if claimed and self.task_store and self.task_id:
                    _, unblocked = self.task_store.complete(
                        self.task_id,
                        self.name,
                    )
                    claimed = False

                    if unblocked:
                        completion = "\nUnblocked: " + ", ".join(
                            item.id for item in unblocked
                        )

                self.status = "idle"
                self._notify(
                    status="completed",
                    output=result + completion,
                )
            except Exception as error:
                if claimed and self.task_store and self.task_id:
                    try:
                        self.task_store.release(self.task_id, self.name)
                    except Exception:
                        pass

                self.status = "idle"
                self._notify(status="failed", output=f"Error: {error}")

    def _notify(self, status: str, output: str) -> None:
        # The manager owns notification storage; this callback is replaced by
        # the manager when the runtime is attached.
        callback = getattr(self, "notification_callback", None)

        if callback:
            callback(self.name, self.role, status, output)

    def start(self) -> None:
        self.thread.start()

    def send(self, content: str) -> None:
        self.inbox.put(content)

    def stop(self) -> None:
        self.inbox.put(None)


class TeamManager:
    def __init__(
        self,
        directory: Path,
        workdir: Path,
        task_store: TaskStore | None = None,
    ):
        self.directory = directory.resolve()
        self.workdir = workdir.resolve()
        self.task_store = task_store
        self._lock = threading.RLock()
        self._teammates: dict[str, TeammateRuntime] = {}
        self._notifications: list[dict] = []

        if not self.directory.is_relative_to(self.workdir):
            raise ValueError(
                "Team directory must stay inside the workspace"
            )

    @staticmethod
    def _callback(
        manager: "TeamManager",
    ) -> Callable[[str, str, str, str], None]:
        def notify(
            name: str,
            role: str,
            status: str,
            output: str,
        ) -> None:
            with manager._lock:
                manager._notifications.append(
                    {
                        "name": name,
                        "role": role,
                        "status": status,
                        "output": output[:12_000],
                    }
                )

        return notify

    def spawn(
        self,
        name: str,
        role: str,
        prompt: str,
        runner: Callable[[str, str], str],
        task_id: str | None = None,
    ) -> Teammate:
        name = name.strip()
        role = role.strip()
        prompt = prompt.strip()

        if not AGENT_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "Teammate name must start with a letter and contain only "
                "letters, digits, underscores, or hyphens"
            )
        if not role or not prompt:
            raise ValueError("Teammate role and prompt cannot be empty")

        with self._lock:
            existing = self._teammates.get(name)

            if existing and existing.status != "stopped":
                raise ValueError(f"Teammate already exists: {name}")

            runtime = TeammateRuntime(
                name=name,
                role=role,
                task_id=task_id,
                runner=runner,
                task_store=self.task_store,
            )
            runtime.notification_callback = self._callback(self)
            self._teammates[name] = runtime
            runtime.start()
            runtime.send(prompt)
            return Teammate(name, role, runtime.status, task_id)

    def send(self, name: str, content: str) -> str:
        if not content.strip():
            raise ValueError("Message cannot be empty")

        with self._lock:
            runtime = self._teammates.get(name)

            if not runtime or runtime.status == "stopped":
                raise ValueError(f"Unknown or stopped teammate: {name}")

            runtime.send(content.strip())
            return f"Queued message for {name}"

    def stop(self, name: str) -> str:
        with self._lock:
            runtime = self._teammates.get(name)

            if not runtime:
                raise ValueError(f"Unknown teammate: {name}")

            runtime.stop()
            return f"Stopping {name}"

    def list_teammates(self) -> list[Teammate]:
        with self._lock:
            return [
                Teammate(
                    name=runtime.name,
                    role=runtime.role,
                    status=runtime.status,
                    task_id=runtime.task_id,
                )
                for runtime in self._teammates.values()
            ]

    def collect_notifications(self) -> list[dict]:
        with self._lock:
            notifications = self._notifications
            self._notifications = []
            return notifications

    def has_pending_notifications(self) -> bool:
        with self._lock:
            return bool(self._notifications)

    def format_list(self) -> str:
        teammates = self.list_teammates()

        if not teammates:
            return "No teammates."

        return "\n".join(
            (
                f"- {item.name} role={item.role} status={item.status} "
                f"task={item.task_id or '(none)'}"
            )
            for item in teammates
        )

    @staticmethod
    def format_notification(notification: dict) -> str:
        return (
            "<teammate_notification>\n"
            f"name: {notification['name']}\n"
            f"role: {notification['role']}\n"
            f"status: {notification['status']}\n"
            f"output:\n{notification['output']}\n"
            "</teammate_notification>"
        )

    def stop_all(self) -> None:
        with self._lock:
            runtimes = list(self._teammates.values())

        for runtime in runtimes:
            if runtime.status != "stopped":
                runtime.stop()

        for runtime in runtimes:
            runtime.thread.join(timeout=2)


def build_team_tools(
    manager: TeamManager,
) -> tuple[list[dict], dict[str, Callable]]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "team_spawn",
                "description": (
                    "Start a persistent teammate that works on prompts "
                    "asynchronously and optionally owns a task."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string", "minLength": 1},
                        "prompt": {"type": "string", "minLength": 1},
                        "task_id": {
                            "type": "string",
                            "pattern": "^task_[0-9a-f]{8}$",
                        },
                    },
                    "required": ["name", "role", "prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "team_send",
                "description": "Send a follow-up message to a teammate.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "content": {"type": "string", "minLength": 1},
                    },
                    "required": ["name", "content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "team_list",
                "description": "List teammates and their current status.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "team_stop",
                "description": "Stop a teammate after its current message.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    def team_send(name: str, content: str) -> str:
        return manager.send(name, content)

    def team_list() -> str:
        return manager.format_list()

    def team_stop(name: str) -> str:
        return manager.stop(name)

    handlers = {
        "team_send": team_send,
        "team_list": team_list,
        "team_stop": team_stop,
    }
    return tools, handlers
