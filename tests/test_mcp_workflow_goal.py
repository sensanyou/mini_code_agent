import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from goal_loop import GoalController
from mcp_plugin import MCPManager
from workflow_runtime import WorkflowRuntime


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **_kwargs):
        content = self.responses.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content)
                )
            ]
        )


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(responses)
        )


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = MCPManager(self.root)

    def tearDown(self):
        self.manager.stop_all()
        self.temp.cleanup()

    def test_stdio_server_tool_is_loaded_and_called(self):
        server = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"
        self.manager.connect(
            "echo",
            sys.executable,
            [str(server)],
        )
        tools, handlers = self.manager.tool_specs()
        names = [tool["function"]["name"] for tool in tools]

        self.assertIn("mcp__echo__echo", names)
        output = handlers["mcp__echo__echo"](text="hello")
        self.assertEqual("echo: hello", output)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workflows = self.root / ".workflows"
        self.workflows.mkdir(parents=True)
        self.workflow_path = self.workflows / "demo.json"
        self.workflow_path.write_text(
            json.dumps(
                {
                    "name": "demo",
                    "steps": [
                        {
                            "id": "inspect",
                            "type": "tool",
                            "tool": "read_file",
                            "arguments": {"path": "README.md"},
                        },
                        {
                            "id": "summarize",
                            "type": "agent",
                            "prompt": "Summarize: {{steps.inspect.output}}",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.root / "README.md").write_text(
            "project notes",
            encoding="utf-8",
        )
        self.runtime = WorkflowRuntime(
            self.root,
            self.workflows / "runs",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_workflow_templates_and_journal(self):
        output = self.runtime.run(
            ".workflows/demo.json",
            agent_runner=lambda prompt, role: f"{role}: {prompt}",
            tool_executor=lambda name, arguments: "project notes",
        )

        self.assertIn("Workflow run_", output)
        self.assertIn("completed", output)
        self.assertIn("project notes", output)
        self.assertEqual(
            1,
            len(list((self.workflows / "runs").glob("run_*.json"))),
        )

    def test_failed_workflow_resumes_from_same_step(self):
        workflow_path = self.workflows / "retry.json"
        workflow_path.write_text(
            json.dumps(
                {
                    "name": "retry",
                    "steps": [
                        {
                            "id": "check",
                            "type": "tool",
                            "tool": "bash",
                            "arguments": {"command": "check"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        attempts = {"count": 0}

        def executor(_name, _arguments):
            attempts["count"] += 1
            return (
                "Error: temporary failure"
                if attempts["count"] == 1
                else "all good"
            )

        failed = self.runtime.run(
            ".workflows/retry.json",
            tool_executor=executor,
        )
        run_id = failed.splitlines()[0].split()[1].rstrip(":")
        self.assertIn("failed", failed)

        resumed = self.runtime.resume(
            run_id,
            tool_executor=executor,
        )
        self.assertIn("completed", resumed)
        self.assertEqual(2, attempts["count"])


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.controller = GoalController(
            self.root / ".goals",
            self.root,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_evaluator_continues_then_completes(self):
        self.controller.set(
            "Fix tests",
            "All tests pass",
            max_turns=3,
        )
        client = FakeClient(
            [
                json.dumps(
                    {"complete": False, "reason": "Tests not run"}
                ),
                json.dumps(
                    {"complete": True, "reason": "Tests pass"}
                ),
            ]
        )

        first = self.controller.evaluate("Changed code", client, "fake")
        self.assertTrue(first.continue_loop)
        self.assertEqual("active", first.status)

        second = self.controller.evaluate("Tests pass", client, "fake")
        self.assertFalse(second.continue_loop)
        self.assertEqual("completed", second.status)
        self.assertEqual("completed", self.controller.get().status)


if __name__ == "__main__":
    unittest.main()
