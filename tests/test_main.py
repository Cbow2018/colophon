"""Tests for the entry point: startup, the loop, and shutting down."""

import logging
import tempfile
import threading
import unittest
from pathlib import Path

from colophon.__main__ import main, run, warn_if_root


class FakeRelay:
    def __init__(self, stop_after, stop):
        self.scans = 0
        self._stop_after = stop_after
        self._stop = stop

    def scan_once(self):
        self.scans += 1
        if self.scans >= self._stop_after:
            self._stop.set()


class RunTests(unittest.TestCase):
    def test_the_loop_runs_until_it_is_asked_to_stop(self):
        stop = threading.Event()
        relay = FakeRelay(stop_after=3, stop=stop)

        run(relay, poll_seconds=0.001, stop=stop)

        self.assertEqual(relay.scans, 3)

    def test_a_relay_asked_to_stop_before_it_starts_does_nothing(self):
        stop = threading.Event()
        stop.set()
        relay = FakeRelay(stop_after=1, stop=stop)

        run(relay, poll_seconds=0.001, stop=stop)

        self.assertEqual(relay.scans, 0)


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        logger = logging.getLogger("colophon")
        handlers = list(logger.handlers)
        self.addCleanup(lambda: logger.handlers.__setitem__(slice(None), handlers))

    def env(self, **extra):
        settings = {
            "COLOPHON_CONFIG": str(self.root / "missing.toml"),
            "COLOPHON_INGEST_DIR": str(self.root / "ingest"),
            "COLOPHON_OUTPUT_DIR": str(self.root / "output"),
            "COLOPHON_BACKUP_DIR": str(self.root / "backups"),
        }
        settings.update(extra)
        return settings

    def test_it_creates_the_folders_and_stops_cleanly(self):
        stop = threading.Event()
        stop.set()

        code = main(env=self.env(), stop=stop)

        self.assertEqual(code, 0)
        self.assertTrue((self.root / "ingest").is_dir())
        self.assertTrue((self.root / "output").is_dir())
        self.assertTrue((self.root / "backups").is_dir())

    def test_a_bad_setting_is_explained_and_stops_the_container(self):
        stop = threading.Event()
        stop.set()

        with self.assertLogs("colophon", level="ERROR") as captured:
            code = main(env=self.env(COLOPHON_POLL_SECONDS="0"), stop=stop)

        self.assertEqual(code, 1)
        self.assertIn("poll_seconds", captured.output[0])

    def test_startup_reports_the_user_it_is_running_as(self):
        stop = threading.Event()
        stop.set()

        with self.assertLogs("colophon", level="INFO") as captured:
            main(env=self.env(), stop=stop)

        first = captured.output[0]
        self.assertIn("uid=", first)
        self.assertIn("gid=", first)
        self.assertIn("dry run", first)


class RootWarningTests(unittest.TestCase):
    def test_running_as_root_is_called_out(self):
        with self.assertLogs("colophon", level="WARNING") as captured:
            warn_if_root(0)

        self.assertIn("root", captured.output[0])

    def test_an_ordinary_user_gets_no_warning(self):
        logger = logging.getLogger("colophon")
        with self.assertNoLogs(logger, level="WARNING"):
            warn_if_root(1000)


if __name__ == "__main__":
    unittest.main()
