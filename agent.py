import json
from types import SimpleNamespace

from openai import OpenAI

from config import MODEL, SYSTEM
from hooks import trigger_hooks
from tools import BASE_TOOLS, BASE_HANDLERS
from todo import TODO_TOOLS, TODO_HANDLERS
from subagent import run_subagent


TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "task",
        "description": (
            "Run an independent subagent with fresh "
            "conversation context and return its final text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "minLength": 1,
                }
            },
            "required": ["prompt"],
        },
    },
}


def execute_tool(
    block,
    handlers: dict,
    client: OpenAI,
) -> str:

    blocked = trigger_hooks(
        "PreToolUse",
        block,
    )

    if blocked:
        return str(blocked)

    handler = handlers.get(block.name)

    try:
        if block.name == "task":
            output = (
                handler(
                    **block.input,
                    client=client,
                )
                if handler
                else f"Unknown: {block.name}"
            )

        else:
            output = (
                handler(**block.input)
                if handler
                else f"Unknown: {block.name}"
            )

    except Exception as e:
        output = f"Error: {e}"

    trigger_hooks(
        "PostToolUse",
        block,
        output,
    )

    return str(output)


def agent_loop(
    messages: list,
    client: OpenAI,
):

    tools = [
        *BASE_TOOLS,
        *TODO_TOOLS,
        TASK_TOOL,
    ]

    handlers = {
        **BASE_HANDLERS,
        **TODO_HANDLERS,
        "task": run_subagent,
    }

    while True:

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
        )

        message = response.choices[0].message

        messages.append(
            message.model_dump(exclude_none=True)
        )

        if not message.tool_calls:
            return message.content

        results = []

        for tool_call in message.tool_calls:

            tool_name = tool_call.function.name

            arguments = json.loads(
                tool_call.function.arguments
            )

            block = SimpleNamespace(
                name=tool_name,
                input=arguments,
                id=tool_call.id,
            )

            output = execute_tool(
                block,
                handlers,
                client,
            )

            print(
                f"> {tool_name}: "
                f"{output[:200]}"
            )

            results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            })

        messages.extend(results)