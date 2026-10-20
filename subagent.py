import json
from types import SimpleNamespace

from openai import OpenAI

from config import MAX_AGENT_TURNS, MODEL, SUB_SYSTEM
from hooks import trigger_hooks
from tools import BASE_HANDLERS, BASE_TOOLS


def execute_subagent_tool(block) -> str:
    blocked = trigger_hooks("PreToolUse", block)

    if blocked:
        return str(blocked)

    handler = BASE_HANDLERS.get(block.name)

    try:
        output = (
            handler(**block.input)
            if handler
            else f"Unknown tool: {block.name}"
        )
    except Exception as error:
        output = f"Error: {error}"

    trigger_hooks("PostToolUse", block, output)
    return str(output)


def run_subagent(
    prompt: str,
    client: OpenAI,
    role: str = "general-purpose subagent",
) -> str:
    print("\n\033[35m[Subagent started]\033[0m")
    system = f"{SUB_SYSTEM}\n\nYour role: {role}"
    messages = [{"role": "user", "content": prompt}]

    for _ in range(MAX_AGENT_TURNS):
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            tools=BASE_TOOLS,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            force = trigger_hooks("Stop", messages)

            if force:
                messages.append(
                    {"role": "user", "content": str(force)}
                )
                continue

            print("\033[35m[Subagent done]\033[0m")
            return message.content or "(no summary)"

        results = []

        for tool_call in message.tool_calls:
            try:
                arguments = json.loads(
                    tool_call.function.arguments
                )

                if not isinstance(arguments, dict):
                    raise ValueError("Arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as error:
                output = f"Invalid tool arguments: {error}"
            else:
                block = SimpleNamespace(
                    name=tool_call.function.name,
                    input=arguments,
                    id=tool_call.id,
                )
                output = execute_subagent_tool(block)

            preview = str(output)[:160]
            print(
                f"  \033[90m[sub] {tool_call.function.name}: "
                f"{preview}\033[0m"
            )
            results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)[:50_000],
                }
            )

        messages.extend(results)

    print("\033[35m[Subagent stopped]\033[0m")
    return (
        f"Subagent stopped after {MAX_AGENT_TURNS} turns "
        "without a final answer."
    )
