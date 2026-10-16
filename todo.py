TODO_ITEMS: list[dict] = []


def todo_write(
    tasks: list[str],
) -> str:

    global TODO_ITEMS

    TODO_ITEMS = [
        {
            "id": index + 1,
            "task": task,
            "status": "pending",
        }
        for index, task in enumerate(tasks)
    ]

    return format_todos()


def todo_update(
    task_id: int,
    status: str,
) -> str:

    allowed = {
        "pending",
        "in_progress",
        "completed",
    }

    if status not in allowed:
        return (
            f"Error: status must be one of "
            f"{sorted(allowed)}"
        )

    for item in TODO_ITEMS:
        if item["id"] == task_id:
            item["status"] = status
            return format_todos()

    return f"Error: unknown task id {task_id}"


def todo_list() -> str:
    return format_todos()


def format_todos() -> str:
    if not TODO_ITEMS:
        return "(no todos)"

    lines = []

    for item in TODO_ITEMS:
        marker = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
        }[item["status"]]

        lines.append(
            f"{marker} {item['id']}. "
            f"{item['task']}"
        )

    return "\n".join(lines)


TODO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": (
                "Create or replace the current task list. "
                "Use this for larger multi-step tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "minItems": 1,
                    }
                },
                "required": ["tasks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_update",
            "description": (
                "Update one Todo item status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer"
                    },
                    "status": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "in_progress",
                            "completed",
                        ],
                    },
                },
                "required": [
                    "task_id",
                    "status",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_list",
            "description": "Show the current Todo list.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


TODO_HANDLERS = {
    "todo_write": todo_write,
    "todo_update": todo_update,
    "todo_list": todo_list,
}