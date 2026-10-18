import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)  # cspell:ignore dotenv


WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"
MODEL = os.environ["MODEL_ID"]

ENVIRONMENT_PROMPT = (
    "Windows: use cmd.exe syntax."
    if os.name == "nt"
    else "Unix-like: use the system shell."
)

SYSTEM = (
    f"You are a coding agent working in {WORKDIR}. "
    f"Environment: {ENVIRONMENT_PROMPT} "
    "Use tools to solve the user's task. "
    "For larger tasks, create a Todo plan and use the task tool for "
    "independent subtasks when useful. "
    "Act, don't explain your internal reasoning."
)

SUB_SYSTEM = (
    f"You are a subagent working in the same workspace: {WORKDIR}. "
    f"Environment: {ENVIRONMENT_PROMPT} "
    "Complete the assigned subtask using the available tools. "
    "Do not delegate to another agent. "
    "Return a concise final summary when finished."
)
