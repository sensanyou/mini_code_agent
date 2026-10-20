import unittest
from types import SimpleNamespace
from unittest.mock import patch

import agent


class FakeAssistant:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=False):
        data = {"role": "assistant", "content": self.content}

        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]

        if exclude_none:
            data = {
                key: value
                for key, value in data.items()
                if value is not None
            }

        return data


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = self.responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)]
        )


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(responses)
        )


class AgentLoopTests(unittest.TestCase):
    def test_tool_call_result_is_appended_before_final_answer(self):
        call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="memory_list",
                arguments="{}",
            ),
        )
        client = FakeClient(
            [
                FakeAssistant(tool_calls=[call]),
                FakeAssistant(content="done"),
            ]
        )
        messages = [{"role": "user", "content": "List memories"}]

        with patch("agent.AUTO_MEMORY_EXTRACTION", False):
            answer = agent.agent_loop(messages, client)

        self.assertEqual("done", answer)
        self.assertEqual(2, len(client.chat.completions.calls))
        second_messages = client.chat.completions.calls[1]["messages"]
        tool_results = [
            item
            for item in second_messages
            if item.get("role") == "tool"
        ]
        self.assertEqual(1, len(tool_results))
        self.assertEqual("call_1", tool_results[0]["tool_call_id"])


if __name__ == "__main__":
    unittest.main()
