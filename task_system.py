import json
import re
import secrets
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


TASK_ID_PATTERN = re.compile(r"^task_[0-9a-f]{8}$")
TASK_STATUSES = ("pending", "in_progress", "completed")


@dataclass(frozen=True)
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]


class TaskStore:
    def __init__(self, directory: Path, workdir: Path):
        self.directory = directory.resolve()
        self.workdir = workdir.resolve()
        self._lock = threading.RLock()

        if not self.directory.is_relative_to(self.workdir):
            raise ValueError("Task directory must stay inside the workspace")

    def _path(self, task_id: str) -> Path:
        if (
            not isinstance(task_id, str)
            or not TASK_ID_PATTERN.fullmatch(task_id)
        ):
            raise ValueError(f"Invalid task ID: {task_id!r}")

        path = (self.directory / f"{task_id}.json").resolve()

        if not path.is_relative_to(self.directory):
            raise ValueError(f"Invalid task ID: {task_id!r}")

        return path

    @staticmethod
    def _atomic_write(path: Path, task: Task) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(task), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def create(self, subject: str, description: str = "") -> Task:
        subject = " ".join(subject.split())

        if not subject:
            raise ValueError("Task subject cannot be empty")

        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)

            for _ in range(100):
                task = Task(
                    id=f"task_{secrets.token_hex(4)}",
                    subject=subject,
                    description=description.strip(),
                    status="pending",
                    owner=None,
                    blockedBy=[],
                )
                path = self._path(task.id)

                try:
                    with path.open("x", encoding="utf-8") as handle:
                        json.dump(
                            asdict(task),
                            handle,
                            ensure_ascii=False,
                            indent=2,
                        )
                    return task
                except FileExistsError:
                    continue

        raise RuntimeError("Could not allocate a unique task ID")

    def save(self, task: Task) -> None:
        if task.status not in TASK_STATUSES:
            raise ValueError(f"Invalid task status: {task.status}")
        self._atomic_write(self._path(task.id), task)

    def load(self, task_id: str) -> Task:
        with self._lock:
            path = self._path(task_id)
            data = json.loads(path.read_text(encoding="utf-8"))
            task = Task(**data)

            if task.id != task_id:
                raise ValueError(
                    f"Task file ID {task.id} does not match {task_id}"
                )
            if task.status not in TASK_STATUSES:
                raise ValueError(f"Invalid task status: {task.status}")
            if any(not TASK_ID_PATTERN.fullmatch(item) for item in task.blockedBy):
                raise ValueError(f"Task {task_id} has an invalid dependency")

            return task

    def list_tasks(self) -> list[Task]:
        with self._lock:
            if not self.directory.exists():
                return []

            tasks = []

            for path in sorted(self.directory.glob("task_*.json")):
                try:
                    tasks.append(self.load(path.stem))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue

            return tasks

    def _depends_on(
        self,
        task_id: str,
        target_id: str,
        visited: set[str] | None = None,
    ) -> bool:
        visited = visited or set()

        if task_id in visited:
            return False

        visited.add(task_id)

        try:
            task = self.load(task_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

        for dependency in task.blockedBy:
            if dependency == target_id:
                return True
            if self._depends_on(dependency, target_id, visited):
                return True

        return False

    def update_dependencies(
        self,
        task_id: str,
        add_blocked_by: list[str],
    ) -> Task:
        if not isinstance(add_blocked_by, list):
            raise ValueError("add_blocked_by must be a list of task IDs")

        with self._lock:
            task = self.load(task_id)

            if task.status != "pending" or task.owner is not None:
                raise ValueError(
                    "Dependencies can only be changed while a task is "
                    "pending and unowned"
                )

            dependencies = list(dict.fromkeys(add_blocked_by))

            for dependency in dependencies:
                if dependency == task_id:
                    raise ValueError("A task cannot depend on itself")
                if not self._path(dependency).is_file():
                    raise ValueError(f"Dependency not found: {dependency}")

            existing = set(task.blockedBy)

            for dependency in dependencies:
                if dependency not in existing and self._depends_on(
                    dependency,
                    task_id,
                ):
                    raise ValueError(
                        f"Dependency cycle detected: {task_id} -> {dependency}"
                    )

            updated = Task(
                **{
                    **asdict(task),
                    "blockedBy": list(
                        dict.fromkeys([*task.blockedBy, *dependencies])
                    ),
                }
            )
            self.save(updated)
            return updated

    def incomplete_dependencies(self, task: Task) -> list[str]:
        incomplete = []

        for dependency in task.blockedBy:
            try:
                if self.load(dependency).status != "completed":
                    incomplete.append(dependency)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                incomplete.append(dependency)

        return incomplete

    def can_start(self, task_id: str) -> bool:
        task = self.load(task_id)
        return (
            task.status == "pending"
            and not self.incomplete_dependencies(task)
        )

    def claim(self, task_id: str, owner: str) -> Task:
        owner = owner.strip()

        if not owner:
            raise ValueError("Task owner cannot be empty")

        with self._lock:
            task = self.load(task_id)

            if task.status != "pending":
                raise ValueError(
                    f"Task {task_id} is {task.status}, cannot claim"
                )

            incomplete = self.incomplete_dependencies(task)

            if incomplete:
                raise ValueError(
                    f"Task {task_id} is blocked by: {', '.join(incomplete)}"
                )

            active = next(
                (
                    candidate
                    for candidate in self.list_tasks()
                    if candidate.owner == owner
                    and candidate.status == "in_progress"
                ),
                None,
            )

            if active:
                raise ValueError(
                    f"{owner} already owns active task {active.id}"
                )

            claimed = Task(
                **{
                    **asdict(task),
                    "status": "in_progress",
                    "owner": owner,
                }
            )
            self.save(claimed)
            return claimed

    def complete(self, task_id: str, owner: str) -> tuple[Task, list[Task]]:
        with self._lock:
            task = self.load(task_id)

            if task.status != "in_progress":
                raise ValueError(
                    f"Task {task_id} is {task.status}, cannot complete"
                )
            if task.owner != owner:
                raise ValueError(
                    f"Task {task_id} is owned by {task.owner}, not {owner}"
                )

            ready_before = {
                candidate.id
                for candidate in self.list_tasks()
                if (
                    candidate.status == "pending"
                    and candidate.blockedBy
                    and not self.incomplete_dependencies(candidate)
                )
            }

            completed = Task(
                **{
                    **asdict(task),
                    "status": "completed",
                }
            )
            self.save(completed)

            newly_unblocked = [
                candidate
                for candidate in self.list_tasks()
                if (
                    candidate.id not in ready_before
                    and candidate.status == "pending"
                    and candidate.blockedBy
                    and not self.incomplete_dependencies(candidate)
                )
            ]

            return completed, newly_unblocked

    def release(self, task_id: str, owner: str) -> Task:
        with self._lock:
            task = self.load(task_id)

            if task.status != "in_progress" or task.owner != owner:
                raise ValueError(
                    f"Task {task_id} is not in_progress for {owner}"
                )

            released = Task(
                **{
                    **asdict(task),
                    "status": "pending",
                    "owner": None,
                }
            )
            self.save(released)
            return released

    def ready(self) -> list[Task]:
        return [
            task
            for task in self.list_tasks()
            if task.status == "pending"
            and not self.incomplete_dependencies(task)
        ]

    def format_list(self) -> str:
        tasks = self.list_tasks()

        if not tasks:
            return "No tasks."

        lines = []

        for task in tasks:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }[task.status]
            dependencies = (
                f" blockedBy={','.join(task.blockedBy)}"
                if task.blockedBy
                else ""
            )
            owner = f" owner={task.owner}" if task.owner else ""
            lines.append(
                f"{marker} {task.id}: {task.subject} "
                f"[{task.status}]{owner}{dependencies}"
            )

        return "\n".join(lines)


def build_task_tools(
    store: TaskStore,
    owner: str = "lead",
) -> tuple[list[dict], dict[str, Callable]]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_create",
                "description": (
                    "Create one persistent task. Create nodes first, then add "
                    "dependencies using the returned runtime IDs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                    },
                    "required": ["subject"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_update",
                "description": (
                    "Add prerequisite task IDs to a pending task."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "pattern": "^task_[0-9a-f]{8}$",
                        },
                        "add_blocked_by": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "pattern": "^task_[0-9a-f]{8}$",
                            },
                            "minItems": 1,
                        },
                    },
                    "required": ["task_id", "add_blocked_by"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_list",
                "description": (
                    "List persistent tasks with status, owner, and dependencies."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_get",
                "description": "Read a persistent task by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "pattern": "^task_[0-9a-f]{8}$",
                        },
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_claim",
                "description": (
                    "Claim a ready task and move it to in_progress."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "pattern": "^task_[0-9a-f]{8}$",
                        },
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": (
                    "Complete the caller's in_progress task and report "
                    "newly unblocked work."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "pattern": "^task_[0-9a-f]{8}$",
                        },
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    def task_create(subject: str, description: str = "") -> str:
        task = store.create(subject, description)
        return f"Created {task.id}: {task.subject}"

    def task_update(task_id: str, add_blocked_by: list[str]) -> str:
        task = store.update_dependencies(task_id, add_blocked_by)
        return (
            f"Updated {task.id} blockedBy="
            f"{','.join(task.blockedBy) or '(none)'}"
        )

    def task_list() -> str:
        return store.format_list()

    def task_get(task_id: str) -> str:
        return json.dumps(
            asdict(store.load(task_id)),
            ensure_ascii=False,
            indent=2,
        )

    def task_claim(task_id: str) -> str:
        task = store.claim(task_id, owner)
        return f"Claimed {task.id} ({task.subject}) as {owner}"

    def task_complete(task_id: str) -> str:
        task, unblocked = store.complete(task_id, owner)
        message = f"Completed {task.id} ({task.subject})"

        if unblocked:
            message += "\nUnblocked: " + ", ".join(
                f"{item.id} ({item.subject})" for item in unblocked
            )

        return message

    handlers = {
        "task_create": task_create,
        "task_update": task_update,
        "task_list": task_list,
        "task_get": task_get,
        "task_claim": task_claim,
        "task_complete": task_complete,
    }
    return tools, handlers
