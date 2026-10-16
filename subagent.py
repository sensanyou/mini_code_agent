from openai import  OpenAI

from config import MODEL, SUB_SYSTEM
from hooks import trigger_hooks
from tools import BASE_TOOLS, BASE_HANDLERS


def extract_text(content) -> str:
    if not isinstance(content, list):
        return str(content)

    return "\n".join(
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text"
    )


def execute_subagent_tool(
    block,
) -> str:

    blocked = trigger_hooks(
        "PreToolUse",
        block,
    )

    if blocked:
        return str(blocked)

    handler = BASE_HANDLERS.get(
        block.name
    )

    try:
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


def run_subagent(
    prompt: str,
    client: OpenAI,
) -> str:

    print(
        "\n\033[35m[Subagent started]\033[0m"
    )

    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    for turn in range(30):

        response = client.messages.create(
            model=MODEL,
            system=SUB_SYSTEM,
            messages=messages,
            tools=BASE_TOOLS,
            max_tokens=8000,
        )

        messages.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        tool_calls = [
            block
            for block in response.content
            if block.type == "tool_use"
        ]

        if not tool_calls:

            force = trigger_hooks(
                "Stop",
                messages,
            )

            if force:
                messages.append(
                    {
                        "role": "user",
                        "content": str(force),
                    }
                )
                continue

            print(
                "\033[35m[Subagent done]\033[0m"
            )

            return (
                extract_text(
                    response.content
                )
                or "(no summary)"
            )

        results = []

        for block in tool_calls:

            output = execute_subagent_tool(
                block
            )

            print(
                f"  \033[90m[sub] "
                f"{block.name}: "
                f"{output[:100]}\033[0m"
            )

            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": results,
            }
        )

    print(
        "\033[35m[Subagent stopped]\033[0m"
    )

    return (
        "Subagent stopped after 30 turns "
        "without a final answer."
    )
