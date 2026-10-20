import os
import queue
import threading

from dotenv import load_dotenv
from openai import OpenAI

from config import MODEL
from hooks import trigger_hooks
from agent import (
    agent_loop,
    has_runtime_work,
    start_runtime,
    stop_runtime,
)

# Importing permissions registers the permission hook.
import permissions  # noqa: F401


def main():

    load_dotenv(
        override=True
    )

    # cspell:ignore DEEPSEEK
    api_key = (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )

    if not api_key:
        print(
            "Missing API credentials. "
            "Set DEEPSEEK_API_KEY or OPENAI_API_KEY in .env."
        )
        return

    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        ),
    )

    print("Mini Code Agent")
    print(
        f"Model: {MODEL}"
    )
    print(
        "Type q, exit, or an empty line to quit.\n"
    )

    history = []
    prompt_queue: queue.Queue[str | None] = queue.Queue()

    def read_prompt() -> None:
        while True:
            try:
                query = input("\033[36ms09+ >> \033[0m")
                prompt_queue.put(query)

                if query.strip().lower() in ("q", "exit", ""):
                    return
            except (EOFError, KeyboardInterrupt):
                prompt_queue.put(None)
                return

    threading.Thread(
        target=read_prompt,
        name="cli-input",
        daemon=True,
    ).start()
    start_runtime()

    try:
        while True:
            try:
                query = prompt_queue.get(timeout=1)
            except queue.Empty:
                if not has_runtime_work():
                    continue

                print("\n\033[90m[Runtime event]\033[0m")
                query = None
                runtime_event = True
            else:
                runtime_event = False

            if query is None and not runtime_event:
                print()
                break

            if not runtime_event:
                if query is None:
                    break

                if query.strip().lower() in (
                    "q",
                    "exit",
                    "",
                ):
                    break

                trigger_hooks(
                    "UserPromptSubmit",
                    query,
                )

                history.append(
                    {
                        "role": "user",
                        "content": query,
                    }
                )

            try:
                answer = agent_loop(
                    history,
                    client,
                )
            except Exception as error:
                print(
                    f"\n\033[31mAgent error:\033[0m {error}\n"
                )
                continue

            print(
                f"\n\033[32mAgent:\033[0m\n"
                f"{answer}\n"
            )
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        stop_runtime()


if __name__ == "__main__":
    main()
