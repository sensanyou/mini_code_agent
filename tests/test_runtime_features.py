import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from agent_teams import TeamManager
from background_tasks import BackgroundManager
from cron_scheduler import CronScheduler, cron_matches, validate_cron
from task_system import TaskStore


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = BackgroundManager(
            self.root / ".background",
            self.root,
        )

    def tearDown(self):
        self.manager.stop_all()
        self.temp.cleanup()

    def test_background_result_is_collected_once(self):
        command = (
            f'"{sys.executable}" -c '
            f'"import time; time.sleep(0.15); print(\'bg-ok\')"'
        )
        task_id = self.manager.start(command)
        record = self.manager.wait(task_id, timeout=10)

        self.assertEqual("completed", record.status)
        notifications = self.manager.collect()
        self.assertEqual(1, len(notifications))
        self.assertIn("bg-ok", notifications[0]["output"])
        self.assertEqual([], self.manager.collect())


class CronTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scheduler = CronScheduler(self.root / ".cron", self.root)

    def tearDown(self):
        self.scheduler.stop()
        self.temp.cleanup()

    def test_validation_and_matching(self):
        self.assertIsNone(validate_cron("0 9 * * 1-5"))
        self.assertIsNotNone(validate_cron("61 9 * * *"))
        moment = datetime(2026, 10, 20, 9, 0)
        cron_weekday = (moment.weekday() + 1) % 7
        self.assertTrue(
            cron_matches(f"0 9 * * {cron_weekday}", moment)
        )

    def test_due_job_is_persisted_and_acknowledged(self):
        job = self.scheduler.schedule(
            "0 9 * * *",
            "Run the morning check",
            recurring=False,
        )
        changed = self.scheduler.poll_due(datetime(2026, 10, 20, 9, 0))

        self.assertEqual(1, changed)
        pending = self.scheduler.pending_jobs()
        self.assertEqual([job.id], [item.id for item in pending])
        self.assertFalse(pending[0].enabled)

        self.scheduler.acknowledge([job.id])
        self.assertEqual([], self.scheduler.pending_jobs())


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tasks = TaskStore(self.root / ".tasks", self.root)
        self.manager = TeamManager(
            self.root / ".teams",
            self.root,
            self.tasks,
        )

    def tearDown(self):
        self.manager.stop_all()
        self.temp.cleanup()

    def test_teammate_completes_assigned_task(self):
        task = self.tasks.create("review")
        self.manager.spawn(
            name="reviewer",
            role="code reviewer",
            prompt="review calculator",
            task_id=task.id,
            runner=lambda prompt, role: f"{role}: {prompt}",
        )

        notifications = []
        deadline = time.monotonic() + 5

        while time.monotonic() < deadline and not notifications:
            notifications = self.manager.collect_notifications()
            time.sleep(0.05)

        self.assertEqual(1, len(notifications))
        self.assertEqual("completed", notifications[0]["status"])
        self.assertEqual("completed", self.tasks.load(task.id).status)


if __name__ == "__main__":
    unittest.main()
