import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from memory import MemoryExtractor, MemoryStore
from task_system import TaskStore


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


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root / ".memory", self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_save_index_search_and_delete(self):
        self.store.save(
            "Python tests",
            "project",
            "Tests use unittest",
            "Run python -m unittest discover -s tests.",
        )

        self.assertIn("Python tests", self.store.index_text())
        self.assertEqual(
            "Python tests",
            self.store.search("How do unittest tests run?")[0].name,
        )
        self.assertTrue(self.store.delete("Python tests"))
        self.assertEqual([], self.store.list_records())

    def test_temporary_memory_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save(
                "temporary",
                "user",
                "Only for this task",
                "Do not create files in the current task.",
            )

    def test_chinese_keyword_recall(self):
        self.store.save(
            "测试偏好",
            "project",
            "项目测试使用 unittest",
            "运行 Python unittest 测试套件。",
        )
        records = self.store.search("项目的测试应该怎么运行")
        self.assertEqual("测试偏好", records[0].name)

    def test_extractor_stores_only_persistent_records(self):
        candidates = """
        [
          {
            "name": "tabs",
            "type": "user",
            "scope": "persistent",
            "description": "User prefers tabs",
            "body": "Use tabs for indentation."
          },
          {
            "name": "one-off",
            "type": "project",
            "scope": "current_task",
            "description": "Temporary",
            "body": "This task must not create files."
          }
        ]
        """
        client = FakeClient([candidates])
        stored = MemoryExtractor(self.store).extract_after_turn(
            [
                {"role": "user", "content": "Remember that I use tabs."},
                {"role": "assistant", "content": "Noted."},
            ],
            client,
            "fake-model",
        )

        self.assertEqual(1, stored)
        self.assertEqual("tabs", self.store.list_records()[0].name)


class TaskSystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TaskStore(self.root / ".tasks", self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_dependency_claim_and_unblock(self):
        schema = self.store.create("schema")
        api = self.store.create("api")
        self.store.update_dependencies(api.id, [schema.id])

        with self.assertRaises(ValueError):
            self.store.claim(api.id, "lead")

        self.store.claim(schema.id, "lead")
        completed, unblocked = self.store.complete(schema.id, "lead")
        self.assertEqual("completed", completed.status)
        self.assertEqual([api.id], [task.id for task in unblocked])

        claimed = self.store.claim(api.id, "lead")
        self.assertEqual("in_progress", claimed.status)

        reloaded = TaskStore(self.root / ".tasks", self.root)
        self.assertEqual("in_progress", reloaded.load(api.id).status)

    def test_cycle_is_rejected(self):
        first = self.store.create("first")
        second = self.store.create("second")
        self.store.update_dependencies(second.id, [first.id])

        with self.assertRaises(ValueError):
            self.store.update_dependencies(first.id, [second.id])

    def test_one_active_task_per_owner(self):
        first = self.store.create("first")
        second = self.store.create("second")
        self.store.claim(first.id, "lead")

        with self.assertRaises(ValueError):
            self.store.claim(second.id, "lead")


if __name__ == "__main__":
    unittest.main()
