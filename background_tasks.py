import json
import os
import secrets
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BackgroundRecord:
    id: str
    command: str
    status: str
    started_at: str
    finished_at: str | None
    exit_code: int | None
    output_file: str
    notified: bool


class BackgroundManager:
    OUTPUT_LIMIT = 50_000

    def __init__(
        self,
        directory: Path,
        workdir: Path,
        timeout: int = 600,
    ):
        self.directory = directory.resolve()
        self.workdir = workdir.resolve()
        self.timeout = timeout
        self.results_dir = self.directory / "results"
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._threads: dict[str, threading.Thread] = {}

        if not self.directory.is_relative_to(self.workdir):
            raise ValueError(
                "Background directory must stay inside the workspace"
            )

        self._recover_stale_records()

    def _path(self, task_id: str) -> Path:
        if (
            not task_id.startswith("bg_")
            or len(task_id) != 11
            or any(character not in "0123456789abcdef" for character in task_id[3:])
        ):
            raise ValueError(f"Invalid background task ID: {task_id!r}")

        path = (self.directory / f"{task_id}.json").resolve()

        if not path.is_relative_to(self.directory):
            raise ValueError(f"Invalid background task ID: {task_id!r}")

        return path

    def _output_path(self, task_id: str) -> Path:
        return self.results_dir / f"{task_id}.log"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def _save(self, record: BackgroundRecord) -> None:
        self._atomic_write(
            self._path(record.id),
            json.dumps(asdict(record), ensure_ascii=False, indent=2),
        )

    def _load(self, task_id: str) -> BackgroundRecord:
        data = json.loads(self._path(task_id).read_text(encoding="utf-8"))
        return BackgroundRecord(**data)

    def _recover_stale_records(self) -> None:
        if not self.directory.exists():
            return

        for path in self.directory.glob("bg_*.json"):
            try:
                record = self._load(path.stem)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue

            if record.status == "running":
                finished = BackgroundRecord(
                    **{
                        **asdict(record),
                        "status": "failed",
                        "finished_at": _utc_now(),
                        "notified": False,
                    }
                )
                self._save(finished)

    def _command_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.setdefault("PYTHONUNBUFFERED", "1")
        return environment

    def _run(self, task_id: str, command: str) -> None:
        output = ""
        exit_code: int | None = None
        status = "failed"

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                env=self._command_environment(),
            )

            with self._lock:
                self._processes[task_id] = process

            try:
                output, _ = process.communicate(timeout=self.timeout)
                exit_code = process.returncode
                status = "completed" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
                output += f"\n\nError: timed out after {self.timeout}s"
                exit_code = -1
                status = "failed"
        except Exception as error:
            output = f"Error: {error}"
            status = "failed"
            exit_code = -1
        finally:
            with self._lock:
                self._processes.pop(task_id, None)
                self._threads.pop(task_id, None)

            output = (output or "(no output)")[: self.OUTPUT_LIMIT]
            self._atomic_write(self._output_path(task_id), output + "\n")

            try:
                record = self._load(task_id)
                finished = BackgroundRecord(
                    **{
                        **asdict(record),
                        "status": status,
                        "finished_at": _utc_now(),
                        "exit_code": exit_code,
                        "notified": False,
                    }
                )
                self._save(finished)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

    def start(self, command: str) -> str:
        command = command.strip()

        if not command:
            raise ValueError("Background command cannot be empty")

        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.results_dir.mkdir(parents=True, exist_ok=True)

            for _ in range(100):
                task_id = f"bg_{secrets.token_hex(4)}"
                path = self._path(task_id)

                if path.exists():
                    continue

                record = BackgroundRecord(
                    id=task_id,
                    command=command,
                    status="running",
                    started_at=_utc_now(),
                    finished_at=None,
                    exit_code=None,
                    output_file=str(self._output_path(task_id)),
                    notified=False,
                )
                self._save(record)
                break
            else:
                raise RuntimeError("Could not allocate a background task ID")

            thread = threading.Thread(
                target=self._run,
                args=(task_id, command),
                name=task_id,
                daemon=True,
            )
            self._threads[task_id] = thread
            thread.start()
            return task_id

    def list_records(self) -> list[BackgroundRecord]:
        with self._lock:
            if not self.directory.exists():
                return []

            records = []

            for path in sorted(self.directory.glob("bg_*.json")):
                try:
                    records.append(self._load(path.stem))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue

            return records

    def get(self, task_id: str) -> BackgroundRecord:
        with self._lock:
            if task_id in self._threads and self._path(task_id).exists():
                return self._load(task_id)
            return self._load(task_id)

    def collect(self) -> list[dict]:
        notifications = []

        with self._lock:
            for record in self.list_records():
                if record.status == "running" or record.notified:
                    continue

                output_path = Path(record.output_file)
                try:
                    output = output_path.read_text(
                        encoding="utf-8"
                    )[:4_000]
                except OSError:
                    output = "(result file unavailable)"

                notifications.append(
                    {
                        "id": record.id,
                        "status": record.status,
                        "exit_code": record.exit_code,
                        "command": record.command,
                        "output": output,
                        "output_file": record.output_file,
                    }
                )
                self._save(
                    BackgroundRecord(
                        **{
                            **asdict(record),
                            "notified": True,
                        }
                    )
                )

        return notifications

    def has_pending_notifications(self) -> bool:
        with self._lock:
            return any(
                record.status != "running" and not record.notified
                for record in self.list_records()
            )

    def wait(self, task_id: str, timeout: float = 30) -> BackgroundRecord:
        deadline = time.monotonic() + max(0, timeout)

        while True:
            record = self._load(task_id)

            if record.status != "running":
                return record

            if time.monotonic() >= deadline:
                return record

            time.sleep(0.1)

    def stop_all(self) -> None:
        with self._lock:
            processes = list(self._processes.values())

        for process in processes:
            if process.poll() is not None:
                continue

            try:
                if os.name == "nt":
                    subprocess.run(
                        [
                            "taskkill",
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                        ],
                        capture_output=True,
                        check=False,
                    )
                else:
                    process.terminate()
            except OSError:
                pass

        with self._lock:
            threads = list(self._threads.values())

        for thread in threads:
            thread.join(timeout=2)

    @staticmethod
    def format_notification(notification: dict) -> str:
        return (
            "<background_task_notification>\n"
            f"id: {notification['id']}\n"
            f"status: {notification['status']}\n"
            f"exit_code: {notification['exit_code']}\n"
            f"command: {notification['command']}\n"
            f"output_file: {notification['output_file']}\n"
            "output:\n"
            f"{notification['output']}\n"
            "</background_task_notification>"
        )

    def format_list(self) -> str:
        records = self.list_records()

        if not records:
            return "No background tasks."

        return "\n".join(
            (
                f"- {record.id} [{record.status}] "
                f"exit={record.exit_code} command={record.command}"
            )
            for record in records
        )


def build_background_tools(
    manager: BackgroundManager,
) -> tuple[list[dict], dict[str, Callable]]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "background_list",
                "description": "List current and finished background tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "background_collect",
                "description": (
                    "Collect completed background task notifications."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    ]

    def background_list() -> str:
        return manager.format_list()

    def background_collect() -> str:
        notifications = manager.collect()

        if not notifications:
            return "(no completed background tasks)"

        return "\n\n".join(
            manager.format_notification(item)
            for item in notifications
        )

    handlers = {
        "background_list": background_list,
        "background_collect": background_collect,
    }
    return tools, handlers
