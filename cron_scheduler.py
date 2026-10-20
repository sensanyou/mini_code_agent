import json
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool
    enabled: bool
    created_at: str
    last_fired: str | None
    pending: bool


def _parse_field(
    field: str,
    minimum: int,
    maximum: int,
    normalize_weekday: bool = False,
) -> set[int] | None:
    if not field:
        return None

    values: set[int] = set()

    for part in field.split(","):
        part = part.strip()

        if not part:
            return None

        step = 1

        if "/" in part:
            base, step_text = part.split("/", 1)

            if not step_text.isdigit() or int(step_text) <= 0:
                return None

            step = int(step_text)
            part = base

        if part == "*":
            start, end = minimum, maximum
        elif "-" in part:
            start_text, end_text = part.split("-", 1)

            if not start_text.isdigit() or not end_text.isdigit():
                return None

            start, end = int(start_text), int(end_text)
        elif part.isdigit():
            start = end = int(part)
        else:
            return None

        if start < minimum or end > maximum or start > end:
            return None

        for value in range(start, end + 1, step):
            if normalize_weekday and value == 7:
                value = 0
            values.add(value)

    return values


def validate_cron(expression: str) -> str | None:
    fields = expression.split()

    if len(fields) != 5:
        return "Cron expression must contain 5 fields"

    limits = (
        (0, 59, False),
        (0, 23, False),
        (1, 31, False),
        (1, 12, False),
        (0, 7, True),
    )
    names = ("minute", "hour", "day", "month", "weekday")

    for field, (minimum, maximum, weekday), name in zip(
        fields,
        limits,
        names,
    ):
        if _parse_field(field, minimum, maximum, weekday) is None:
            return f"Invalid {name} field: {field}"

    return None


def cron_matches(expression: str, moment: datetime) -> bool:
    if validate_cron(expression):
        return False

    minute, hour, day, month, weekday = expression.split()
    minute_values = _parse_field(minute, 0, 59) or set()
    hour_values = _parse_field(hour, 0, 23) or set()
    day_values = _parse_field(day, 1, 31) or set()
    month_values = _parse_field(month, 1, 12) or set()
    weekday_values = _parse_field(weekday, 0, 7, True) or set()
    cron_weekday = (moment.weekday() + 1) % 7

    if (
        moment.minute not in minute_values
        or moment.hour not in hour_values
        or moment.month not in month_values
    ):
        return False

    day_matches = moment.day in day_values
    weekday_matches = cron_weekday in weekday_values

    # Traditional cron uses OR when day-of-month and day-of-week are both
    # restricted, and the unrestricted field otherwise.
    day_restricted = day != "*"
    weekday_restricted = weekday != "*"

    if day_restricted and weekday_restricted:
        return day_matches or weekday_matches

    return day_matches and weekday_matches


class CronScheduler:
    POLL_SECONDS = 15

    def __init__(self, directory: Path, workdir: Path):
        self.directory = directory.resolve()
        self.workdir = workdir.resolve()
        self.jobs_path = self.directory / "jobs.json"
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        if not self.directory.is_relative_to(self.workdir):
            raise ValueError("Cron directory must stay inside the workspace")

    def _load(self) -> list[CronJob]:
        if not self.jobs_path.exists():
            return []

        try:
            data = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        jobs = []

        for item in data if isinstance(data, list) else []:
            try:
                job = CronJob(**item)
            except (TypeError, ValueError):
                continue

            if validate_cron(job.cron) is None:
                jobs.append(job)

        return jobs

    def _save(self, jobs: list[CronJob]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.jobs_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                [asdict(job) for job in jobs],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.jobs_path)

    def schedule(
        self,
        expression: str,
        prompt: str,
        recurring: bool = True,
    ) -> CronJob:
        expression = " ".join(expression.split())
        prompt = prompt.strip()
        error = validate_cron(expression)

        if error:
            raise ValueError(error)
        if not prompt:
            raise ValueError("Scheduled prompt cannot be empty")

        with self._lock:
            jobs = self._load()

            if len(jobs) >= 100:
                raise ValueError("Cron job limit reached")

            job = CronJob(
                id=f"cron_{secrets.token_hex(4)}",
                cron=expression,
                prompt=prompt,
                recurring=bool(recurring),
                enabled=True,
                created_at=datetime.now().isoformat(timespec="seconds"),
                last_fired=None,
                pending=False,
            )
            jobs.append(job)
            self._save(jobs)
            return job

    def list_jobs(self) -> list[CronJob]:
        with self._lock:
            return self._load()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            jobs = self._load()
            remaining = [job for job in jobs if job.id != job_id]

            if len(remaining) == len(jobs):
                return False

            self._save(remaining)
            return True

    def poll_due(self, moment: datetime | None = None) -> int:
        moment = moment or datetime.now()
        marker = moment.strftime("%Y-%m-%dT%H:%M")
        changed = 0

        with self._lock:
            jobs = self._load()
            updated = []

            for job in jobs:
                if (
                    job.enabled
                    and job.last_fired != marker
                    and cron_matches(job.cron, moment)
                ):
                    updated.append(
                        CronJob(
                            **{
                                **asdict(job),
                                "last_fired": marker,
                                "pending": True,
                                "enabled": job.enabled and job.recurring,
                            }
                        )
                    )
                    changed += 1
                else:
                    updated.append(job)

            if changed:
                self._save(updated)

        return changed

    def pending_jobs(self) -> list[CronJob]:
        with self._lock:
            return [job for job in self._load() if job.pending]

    def has_pending_jobs(self) -> bool:
        return bool(self.pending_jobs())

    def acknowledge(self, job_ids: list[str]) -> None:
        acknowledged = set(job_ids)

        with self._lock:
            jobs = self._load()
            self._save(
                [
                    CronJob(
                        **{
                            **asdict(job),
                            "pending": (
                                False
                                if job.id in acknowledged
                                else job.pending
                            ),
                        }
                    )
                    for job in jobs
                ]
            )

    def _loop(self) -> None:
        while not self._stop_event.wait(self.POLL_SECONDS):
            try:
                self.poll_due()
            except Exception as error:
                print(f"[Cron scheduler error: {error}]")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="cron-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=2)

    def format_jobs(self) -> str:
        jobs = self.list_jobs()

        if not jobs:
            return "No cron jobs."

        return "\n".join(
            (
                f"- {job.id} [{job.cron}] "
                f"recurring={job.recurring} enabled={job.enabled} "
                f"pending={job.pending} prompt={job.prompt[:120]}"
            )
            for job in jobs
        )


def build_cron_tools(
    scheduler: CronScheduler,
) -> tuple[list[dict], dict[str, Callable]]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "cron_schedule",
                "description": (
                    "Schedule a prompt with a standard 5-field cron expression."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cron": {
                            "type": "string",
                            "description": (
                                "minute hour day-of-month month weekday"
                            ),
                        },
                        "prompt": {"type": "string", "minLength": 1},
                        "recurring": {"type": "boolean"},
                    },
                    "required": ["cron", "prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cron_list",
                "description": "List scheduled cron jobs.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cron_cancel",
                "description": "Cancel a cron job by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "pattern": "^cron_[0-9a-f]{8}$",
                        },
                    },
                    "required": ["job_id"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    def cron_schedule(
        cron: str,
        prompt: str,
        recurring: bool = True,
    ) -> str:
        job = scheduler.schedule(cron, prompt, recurring)
        return (
            f"Scheduled {job.id}: {job.cron} "
            f"(recurring={job.recurring})"
        )

    def cron_list() -> str:
        return scheduler.format_jobs()

    def cron_cancel(job_id: str) -> str:
        if scheduler.cancel(job_id):
            return f"Cancelled {job_id}"
        return f"Cron job not found: {job_id}"

    handlers = {
        "cron_schedule": cron_schedule,
        "cron_list": cron_list,
        "cron_cancel": cron_cancel,
    }
    return tools, handlers
