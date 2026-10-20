import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)  # cspell:ignore dotenv


WORKDIR = Path(
    os.environ.get("MINI_AGENT_WORKDIR", Path.cwd())
).resolve()
SKILLS_DIR = WORKDIR / "skills"
MEMORY_DIR = WORKDIR / ".memory"
TASKS_DIR = WORKDIR / ".tasks"
BACKGROUND_DIR = WORKDIR / ".background"
CRON_DIR = WORKDIR / ".cron"
TEAM_DIR = WORKDIR / ".teams"
GOALS_DIR = WORKDIR / ".goals"
WORKFLOW_DIR = WORKDIR / ".workflows"

MODEL = os.environ.get("MODEL_ID", "deepseek-chat")
AGENT_NAME = os.environ.get("MINI_AGENT_NAME", "lead")
MAX_AGENT_TURNS = int(os.environ.get("MAX_AGENT_TURNS", "50"))
AUTO_MEMORY_EXTRACTION = os.environ.get(
    "AUTO_MEMORY_EXTRACTION",
    "true",
).lower() in ("1", "true", "yes", "on")

ENVIRONMENT_PROMPT = (
    "Windows: use cmd.exe syntax."
    if os.name == "nt"
    else "Unix-like: use the system shell."
)

SYSTEM = (
    f"You are a coding agent working in {WORKDIR}. "
    f"Environment: {ENVIRONMENT_PROMPT} "
    "Use tools to solve the user's task. "
    "For larger tasks, create a Todo plan and use the task system for "
    "persistent work with dependencies. Use the task tool for independent "
    "subtasks when useful. Use background tasks for slow shell commands. "
    "Use memory tools when durable preferences or project facts should "
    "survive the current session. "
    "Act, don't explain your internal reasoning."
)

SUB_SYSTEM = (
    f"You are a subagent working in the same workspace: {WORKDIR}. "
    f"Environment: {ENVIRONMENT_PROMPT} "
    "Complete the assigned subtask using the available tools. "
    "Do not delegate to another agent. "
    "Return a concise final summary when finished."
)
