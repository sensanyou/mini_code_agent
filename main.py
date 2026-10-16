import os

from openai import OpenAI
# cspell:ignore dotenv
from dotenv import load_dotenv

from config import MODEL
from hooks import trigger_hooks
from agent import agent_loop

# Importing permissions registers the permission hook.
import permissions  # noqa: F401


def main():

    load_dotenv(
        override=True
    )

    # cspell:ignore DEEPSEEK
    if not os.environ.get(
        "DEEPSEEK_API_KEY"
    ) and not os.environ.get(
        "ANTHROPIC_AUTH_TOKEN"
    ):
        print(
            "Missing API credentials. "
            "Set DEEPSEEK_API_KEY in .env."
        )
        return

    client = OpenAI(
        api_key=os.environ.get(
            "DEEPSEEK_API_KEY"
        ),
        base_url=
            os.environ.get(
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

    while True:

        try:
            query = input(
                "\033[36ms06 >> \033[0m"
            )

        except (
            EOFError,
            KeyboardInterrupt,
        ):
            print()
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

        answer = agent_loop(
            history,
            client,
        )

        print(
            f"\n\033[32mAgent:\033[0m\n"
            f"{answer}\n"
        )


if __name__ == "__main__":
    main()
