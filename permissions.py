import re

from config import WORKDIR
from hooks import register_hook


DENY_LIST = [
    "rm -rf /",
    "sudo",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    "> /dev/sda",
]


def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return (
                f"Blocked: '{pattern}' "
                "is on the deny list"
            )

    return None


DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*"
    r"(?:rm|del)"
    r"(?=\s|$|[;&|()])"
)


def contains_destructive_command(command: str) -> bool:
    return bool(
        DESTRUCTIVE_COMMAND_WORD.search(command)
    )


PERMISSION_RULES = [
    {
        "tools": [
            "read_file",
            "write_file",
            "edit_file",
        ],
        "check": (
            lambda args:
            not (
                WORKDIR
                / args.get("path", "")
            )
            .resolve()
            .is_relative_to(WORKDIR)
        ),
        "message": "Access outside workspace",
    },
    {
        "tools": ["bash"],
        "check": (
            lambda args:
            contains_destructive_command(
                args.get("command", "")
            )
            or any(
                kw in args.get("command", "")
                for kw in [
                    "rm ",
                    "> /etc/",
                    "chmod 777",
                ]
            )
        ),
        "message": "Potentially destructive command",
    },
]


def check_rules(
    tool_name: str,
    args: dict,
) -> str | None:

    for rule in PERMISSION_RULES:
        if (
            tool_name in rule["tools"]
            and rule["check"](args)
        ):
            return rule["message"]

    return None


def ask_user(
    tool_name: str,
    args: dict,
    reason: str,
) -> str:

    print(f"\n⚠ {reason}")
    print(
        f"  Tool: {tool_name}({args})"
    )

    choice = input(
        "  Allow? [y/N] "
    ).strip().lower()

    return (
        "allow"
        if choice in ("y", "yes")
        else "deny"
    )


def permission_hook(block):
    if block.name == "bash":
        reason = check_deny_list(
            block.input.get("command", "")
        )

        if reason:
            print(
                f"\n⛔ {reason}"
            )
            return reason

    reason = check_rules(
        block.name,
        block.input,
    )

    if reason:
        decision = ask_user(
            block.name,
            block.input,
            reason,
        )

        if decision == "deny":
            return (
                "Permission denied by user."
            )

    return None


register_hook(
    "PreToolUse",
    permission_hook,
)
