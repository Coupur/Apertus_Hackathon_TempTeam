"""Power-control safety checks; no test can call the real shutdown API."""
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from navigator.focused.power import WindowsPower, completed_export, watch


START = "2026-10-18T22:05:33+00:00"
FINISH = "2026-10-19T02:00:00+00:00"


def final_report(**changes):
    return {"started_at": START, "finished_at": FINISH, "stopping_reason": "frontier_exhausted",
            "pending_urls": 0, "retained_findings": 1, **changes}


def export_for(report):
    return {"count": 1, "findings": [{"id": "retained-finding"}], "last_run": report}


class CompletionChecks(unittest.TestCase):
    def test_accepts_saved_completion_even_with_unavailable_source_pages(self):
        report = final_report(errors={"http_404": 3}, exhaustive=False)
        self.assertEqual(completed_export(report, export_for(report), START), 1)

    def test_rejects_interruption_budget_running_pending_and_wrong_run(self):
        for changes in ({"stopping_reason": "interrupted"}, {"stopping_reason": "fetch_budget"},
                        {"stopping_reason": "running"}, {"pending_urls": 1},
                        {"finished_at": None}, {"started_at": "2026-10-17T22:05:33+00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                report = final_report(**changes)
                completed_export(report, export_for(report), START)

    def test_rejects_stale_export_and_partial_or_empty_findings(self):
        report = final_report()
        for export in (
            {**export_for(report), "last_run": final_report(finished_at="2026-10-18T23:00:00+00:00")},
            {**export_for(report), "count": 2},
            {**export_for(report), "findings": []},
            {**export_for(report), "findings": None},
        ):
            with self.subTest(export=export), self.assertRaises(ValueError):
                completed_export(report, export, START)

    def test_rejects_invalid_completion_time(self):
        for finish in ("2026-10-17T02:00:00+00:00", "2026-10-19T02:00:00"):
            with self.subTest(finish=finish), self.assertRaises(ValueError):
                report = final_report(finished_at=finish)
                completed_export(report, export_for(report), START)

    def test_shutdown_api_explicitly_preserves_unsaved_apps_and_does_not_restart(self):
        system = object.__new__(WindowsPower)
        call = Mock(return_value=1)
        system.advapi = SimpleNamespace(InitiateSystemShutdownExW=call)
        system.shutdown(120)
        arguments = call.call_args.args
        self.assertEqual(arguments[2], 120)
        self.assertIs(arguments[3], False)
        self.assertIs(arguments[4], False)


class FakePower:
    def __init__(self):
        self.running = True
        self.awake = False
        self.opened = set()
        self.enable_shutdown = Mock()
        self.shutdown = Mock()
        self.codes = {1234: 0, 5678: 0}

    @contextmanager
    def process(self, pid):
        self.opened.add(pid)
        try:
            yield pid
        finally:
            self.opened.remove(pid)

    @contextmanager
    def keep_awake(self):
        self.awake = True
        try:
            yield
        finally:
            self.awake = False

    def exit_code(self, pid):
        return None if self.running else self.codes[pid]


class WatchChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.metadata_path = root / "active.json"
        self.state_path = root / "power.json"
        self.report_path = root / "report.json"
        self.export_path = root / "export.json"
        self.metadata = {"pid": 1234, "started_at": "2026-10-18T22:05:26+00:00",
                         "working_directory": str(root), "report": str(self.report_path),
                         "export": str(self.export_path)}
        self.write(self.metadata_path, self.metadata)
        self.write(self.report_path, final_report(stopping_reason="running", finished_at=None, pending_urls=5))
        self.system = FakePower()
        self.discovery = patch("navigator.focused.power.discover_processes", return_value=[1234, 5678])
        self.discovery.start()
        self.addCleanup(self.discovery.stop)

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def complete(self, **changes):
        report = final_report(**changes)
        self.write(self.report_path, report)
        self.write(self.export_path, export_for(report))
        self.system.running = False

    def run_watch(self, shutdown=True, sleep=None):
        with patch("builtins.print"):
            watch(self.metadata_path, self.state_path, self.system, shutdown, 120,
                  sleep=sleep or (lambda _: self.complete()))

    def assert_released(self):
        self.assertFalse(self.system.awake)
        self.assertEqual(self.system.opened, set())

    def test_success_waits_for_processes_and_export_then_schedules_once(self):
        intervals = []

        def advance(seconds):
            intervals.append(seconds)
            self.assertTrue(self.system.awake)
            if seconds == 10:
                self.system.shutdown.assert_not_called()
                self.complete()
            else:
                self.system.shutdown.assert_called_once_with(120)

        self.run_watch(sleep=advance)
        self.assertEqual(intervals, [10, 120])
        self.assertEqual(json.loads(self.state_path.read_text())["status"], "shutdown_scheduled")
        self.assert_released()

    def test_shutdown_is_opt_in(self):
        self.run_watch(shutdown=False)
        self.system.enable_shutdown.assert_not_called()
        self.system.shutdown.assert_not_called()
        self.assert_released()

    def test_nonzero_exit_does_not_shutdown_even_with_complete_report(self):
        self.system.codes[5678] = 1
        with self.assertRaises(ValueError):
            self.run_watch()
        self.system.shutdown.assert_not_called()
        self.assert_released()

    def test_interrupted_crawl_does_not_shutdown(self):
        with self.assertRaises(ValueError):
            self.run_watch(sleep=lambda _: self.complete(stopping_reason="interrupted"))
        self.system.shutdown.assert_not_called()
        self.assert_released()

    def test_missing_export_does_not_shutdown(self):
        def finish_without_export(_):
            self.complete()
            self.export_path.unlink()

        with self.assertRaises(FileNotFoundError):
            self.run_watch(sleep=finish_without_export)
        self.system.shutdown.assert_not_called()
        self.assert_released()

    def test_metadata_replacement_cancels_old_run_guard(self):
        def replace_run(_):
            self.write(self.metadata_path, {**self.metadata, "pid": 9999})

        with self.assertRaises(ValueError):
            self.run_watch(sleep=replace_run)
        self.system.shutdown.assert_not_called()
        self.assert_released()

    def test_cancel_marker_releases_sleep_guard_without_stopping_crawler(self):
        self.state_path.with_suffix(".cancel").touch()
        self.run_watch()
        self.assertTrue(self.system.running)
        self.system.shutdown.assert_not_called()
        self.assertEqual(json.loads(self.state_path.read_text())["status"], "cancelled")
        self.assert_released()

    def test_guard_cannot_arm_using_a_previous_run_report(self):
        self.write(self.report_path, final_report(started_at="2026-10-17T22:05:33+00:00",
                                                stopping_reason="running", finished_at=None))
        with self.assertRaises(ValueError):
            self.run_watch()
        self.system.shutdown.assert_not_called()
        self.assert_released()

    def test_permission_failure_does_not_schedule_shutdown(self):
        self.system.enable_shutdown.side_effect = OSError("Shutdown privilege unavailable")
        with self.assertRaises(OSError):
            self.run_watch()
        self.system.shutdown.assert_not_called()
        self.assert_released()


if __name__ == "__main__":
    unittest.main()
