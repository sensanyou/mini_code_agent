import glob as glob_module
import subprocess
from pathlib import Path

from config import WORKDIR


def safe_path(path_text: str) -> Path:
    path = (WORKDIR / path_text).resolve()

    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path_text}")

    return path


def run_bash(command: str) -> str:
    dangerous = [
        "rm -rf /",
        "sudo",
        "shutdown",
        "reboot",
        "mkfs",
        "dd if=",
        "> /dev/sda",
    ]

    if any(pattern in command for pattern in dangerous):
        return "Error: Dangerous command blocked"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )

        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(no output)"

    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()

        if limit and limit < len(lines):
            lines = lines[:limit] + [
                f"... ({len(lines) - limit} more lines)"
            ]

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path.write_text(
            content,
            encoding="utf-8",
        )

        return f"Wrote {len(content)} bytes to {path}"

    except Exception as e:
        return f"Error: {e}"


def run_edit(
    path: str,
    old_text: str,
    new_text: str,
) -> str:
    try:
        file_path = safe_path(path)

        text = file_path.read_text(
            encoding="utf-8"
        )

        if old_text not in text:
            return f"Error: text not found in {path}"

        file_path.write_text(
            text.replace(old_text, new_text, 1),
            encoding="utf-8",
        )

        return f"Edited {path}"

    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:
    try:
        matches = sorted(
            {
                match
                for match in glob_module.glob(
                    pattern,
                    root_dir=WORKDIR,
                    recursive=True,
                )
                if (
                    WORKDIR / match
                ).resolve().is_relative_to(WORKDIR)
            }
        )

        shown = matches[:200]

        if len(matches) > 200:
            shown.append(
                "... (more matches omitted; narrow the pattern)"
            )

        return (
            "\n".join(shown)
            if shown
            else "(no matches)"
        )

    except Exception as e:
        return f"Error: {e}"


BASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string"
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "limit": {
                        "type": "integer"
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write UTF-8 content to a file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "content": {
                        "type": "string"
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text once in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string"
                    },
                    "old_text": {
                        "type": "string"
                    },
                    "new_text": {
                        "type": "string"
                    },
                },
                "required": [
                    "path",
                    "old_text",
                    "new_text",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": (
                "Find files matching a glob pattern. "
                "** matches recursively."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string"
                    }
                },
                "required": ["pattern"],
            },
        },
    },
]


BASE_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
}