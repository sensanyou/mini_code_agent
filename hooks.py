from collections import defaultdict

from config import WORKDIR


HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}


def register_hook(event: str, callback):
    if event not in HOOKS:
        raise ValueError(f"Unknown hook event: {event}")

    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)

        if result is not None:
            return result

    return None


def context_hook(query: str) -> None:
    print(
        f"\033[90m[HOOK] UserPromptSubmit: "
        f"workspace={WORKDIR}\033[0m"
    )


def log_tool_hook(block) -> None:
    print(
        f"\033[90m[HOOK] PreToolUse: "
        f"{block.name}\033[0m"
    )


def large_output_hook(block, output) -> None:
    if len(str(output)) > 100000:
        print(
            f"\033[33m[HOOK] Large output from "
            f"{block.name}\033[0m"
        )


def summary_hook(messages: list) -> None:
    tool_count = 0

    for message in messages:
        if message.get("role") == "assistant":
            tool_count += len(message.get("tool_calls", []) or [])

        content = message.get("content")

        if isinstance(content, list):
            tool_count += sum(
                1
                for block in content
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                )
            )

    print(
        f"\033[90m[HOOK] Stop: "
        f"{tool_count} tool call(s) in this conversation\033[0m"
    )


register_hook(
    "UserPromptSubmit",
    context_hook,
)

# Permission is registered from permissions.py
# to keep the permission logic separate.

register_hook(
    "PreToolUse",
    log_tool_hook,
)

register_hook(
    "PostToolUse",
    large_output_hook,
)

register_hook(
    "Stop",
    summary_hook,
)
