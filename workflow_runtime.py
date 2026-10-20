import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Callable


TEMPLATE_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _lookup(context: dict, path: str) -> str:
    value = context

    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return ""
        value = value[part]

    return str(value)


def render_value(value, context: dict):
    if isinstance(value, str):
        return TEMPLATE_PATTERN.sub(
            lambda match: _lookup(context, match.group(1)),
            value,
        )

    if isinstance(value, list):
        return [render_value(item, context) for item in value]

    if isinstance(value, dict):
        return {
            key: render_value(item, context)
            for key, item in value.items()
        }

    return value


class WorkflowRuntime:
    def __init__(self, workdir: Path, runs_dir: Path):
        self.workdir = workdir.resolve()
        self.runs_dir = runs_dir.resolve()

        if not self.runs_dir.is_relative_to(self.workdir):
            raise ValueError(
                "Workflow runs directory must stay inside the workspace"
            )

    def _workflow_path(self, workflow_path: str) -> Path:
        path = (self.workdir / workflow_path).resolve()

        if not path.is_relative_to(self.workdir):
            raise ValueError("Workflow path escapes the workspace")
        if not path.is_file():
            raise FileNotFoundError(f"Workflow not found: {workflow_path}")
        if path.suffix.lower() != ".json":
            raise ValueError("Workflow files must use the .json extension")

        return path

    def _run_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"run_[A-Za-z0-9_-]{6,80}", run_id):
            raise ValueError(f"Invalid workflow run ID: {run_id!r}")

        path = (self.runs_dir / f"{run_id}.json").resolve()

        if not path.is_relative_to(self.runs_dir):
            raise ValueError(f"Invalid workflow run ID: {run_id!r}")

        return path

    def _save(self, state: dict) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = _now()
        path = self._run_path(state["run_id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _load(self, run_id: str) -> dict:
        path = self._run_path(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_workflow(path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            raise ValueError("Workflow root must be a JSON object")

        steps = data.get("steps")

        if not isinstance(steps, list) or not steps:
            raise ValueError("Workflow must contain a non-empty steps list")

        seen_ids = set()

        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"Workflow step {index} must be an object")

            step_id = str(step.get("id", "")).strip()
            step_type = str(step.get("type", "")).strip()

            if not step_id or step_id in seen_ids:
                raise ValueError(
                    f"Workflow step {index} has an empty or duplicate id"
                )
            if step_type not in ("agent", "tool"):
                raise ValueError(
                    f"Workflow step {step_id} has invalid type {step_type!r}"
                )

            seen_ids.add(step_id)

        return data

    @staticmethod
    def _workflow_failed(output: str) -> bool:
        prefix = output.strip().lower()
        return (
            prefix.startswith("error:")
            or prefix.startswith("permission denied")
            or prefix.startswith("blocked:")
        )

    def run(
        self,
        workflow_path: str,
        inputs: dict | None = None,
        agent_runner: Callable[[str, str], str] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
    ) -> str:
        path = self._workflow_path(workflow_path)
        workflow = self._load_workflow(path)
        run_id = (
            f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
            f"{secrets.token_hex(3)}"
        )
        state = {
            "run_id": run_id,
            "workflow_path": str(path.relative_to(self.workdir)),
            "name": str(workflow.get("name") or path.stem),
            "inputs": inputs or {},
            "steps": {},
            "next_index": 0,
            "status": "running",
            "error": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._save(state)
        return self._execute(
            state,
            workflow,
            agent_runner,
            tool_executor,
        )

    def resume(
        self,
        run_id: str,
        agent_runner: Callable[[str, str], str] | None = None,
        tool_executor: Callable[[str, dict], str] | None = None,
    ) -> str:
        state = self._load(run_id)
        path = self._workflow_path(state["workflow_path"])
        workflow = self._load_workflow(path)

        if state.get("status") == "completed":
            return self._format_state(state)

        state["status"] = "running"
        state["error"] = ""
        self._save(state)
        return self._execute(
            state,
            workflow,
            agent_runner,
            tool_executor,
        )

    def _execute(
        self,
        state: dict,
        workflow: dict,
        agent_runner: Callable[[str, str], str] | None,
        tool_executor: Callable[[str, dict], str] | None,
    ) -> str:
        steps = workflow["steps"]
        context = {
            "inputs": state.get("inputs", {}),
            "steps": state.get("steps", {}),
        }

        try:
            for index in range(int(state.get("next_index", 0)), len(steps)):
                step = steps[index]
                step_id = step["id"]
                step_type = step["type"]
                rendered = render_value(step, context)

                if step_type == "agent":
                    if not agent_runner:
                        raise RuntimeError("No agent runner configured")

                    prompt = str(rendered.get("prompt", "")).strip()
                    role = str(rendered.get("role", "workflow worker")).strip()

                    if not prompt:
                        raise ValueError(
                            f"Agent step {step_id} has an empty prompt"
                        )

                    output = agent_runner(prompt, role)
                else:
                    if not tool_executor:
                        raise RuntimeError("No tool executor configured")

                    tool_name = str(rendered.get("tool", "")).strip()
                    arguments = rendered.get("arguments", {})

                    if not tool_name or not isinstance(arguments, dict):
                        raise ValueError(
                            f"Tool step {step_id} needs tool and arguments"
                        )

                    output = tool_executor(tool_name, arguments)

                output = str(output)
                state["steps"][step_id] = {
                    "type": step_type,
                    "output": output,
                }
                context["steps"] = state["steps"]
                failed = self._workflow_failed(output)
                should_continue = (
                    not failed
                    or bool(step.get("continue_on_error", False))
                )
                state["next_index"] = (
                    index + 1
                    if should_continue
                    else index
                )
                self._save(state)

                if not should_continue:
                    raise RuntimeError(
                        f"Workflow step {step_id} failed: {output[:1_000]}"
                    )

            state["status"] = "completed"
            state["error"] = ""
            self._save(state)
            return self._format_state(state)
        except Exception as error:
            state["status"] = "failed"
            state["error"] = str(error)
            self._save(state)
            return (
                f"Workflow {state['run_id']} failed: {error}\n"
                f"Resume with workflow_resume(run_id='{state['run_id']}')."
            )

    @staticmethod
    def _format_state(state: dict) -> str:
        lines = [
            f"Workflow {state['run_id']}: {state['status']}",
            f"Name: {state.get('name', '')}",
            f"Progress: {state.get('next_index', 0)} step(s)",
        ]

        if state.get("error"):
            lines.append(f"Error: {state['error']}")

        for step_id, result in state.get("steps", {}).items():
            output = str(result.get("output", ""))
            lines.append(f"[{step_id}] {output[:2_000]}")

        return "\n".join(lines)

    def list_runs(self, limit: int = 20) -> str:
        if not self.runs_dir.exists():
            return "No workflow runs."

        runs = []

        for path in self.runs_dir.glob("run_*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            runs.append(
                (
                    str(state.get("updated_at", "")),
                    state.get("run_id", path.stem),
                    state.get("name", ""),
                    state.get("status", ""),
                )
            )

        runs.sort(reverse=True)
        return "\n".join(
            f"- {run_id} [{status}] {name}"
            for _, run_id, name, status in runs[:limit]
        ) or "No workflow runs."


def build_workflow_tools(
    runtime: WorkflowRuntime,
) -> tuple[list[dict], dict[str, Callable]]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "workflow_run",
                "description": (
                    "Run a saved JSON workflow of agent and tool steps with "
                    "a resumable journal."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_path": {"type": "string", "minLength": 1},
                        "inputs": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["workflow_path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workflow_resume",
                "description": (
                    "Resume a failed workflow run from its saved journal."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "minLength": 1},
                    },
                    "required": ["run_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workflow_list",
                "description": "List saved workflow runs.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    ]

    def workflow_list() -> str:
        return runtime.list_runs()

    handlers = {
        "workflow_list": workflow_list,
    }
    return tools, handlers
