"""Tests for the entry point: startup, the loop, and shutting down."""

import logging
import threading
import unittest
from pathlib import Path

from colophon.__main__ import main, run, warn_if_root
from colophon.record import Record
from tests.tempdir import TemporaryDirectory


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


class ResetRecordTests(unittest.TestCase):
    """The one command that empties the record, and the question it asks first."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        logger = logging.getLogger("colophon")
        handlers = list(logger.handlers)
        self.addCleanup(lambda: logger.handlers.__setitem__(slice(None), handlers))

        self.path = self.root / "record.db"
        self.record = Record.open(self.path)
        self.record.save(self.record.resolve("author", ("L.J. Ross",), "hardcover"))
        self.record.close()

    def env(self):
        return {
            "COLOPHON_CONFIG": str(self.root / "missing.toml"),
            "COLOPHON_RECORD_PATH": str(self.path),
        }

    def main(self, arguments, answer=""):
        stop = threading.Event()
        stop.set()
        return main(
            env=self.env(),
            argv=arguments,
            stop=stop,
            stdin=_Input(answer),
        )

    def names(self):
        opened = Record.open(self.path)
        self.addCleanup(opened.close)
        return opened.names()

    def test_yes_empties_the_record_without_asking(self):
        code = self.main(["--reset-record", "--yes"])

        self.assertEqual(code, 0)
        self.assertEqual(self.names(), ())

    def test_an_answered_question_empties_it(self):
        code = self.main(["--reset-record"], answer="y\n")

        self.assertEqual(code, 0)
        self.assertEqual(self.names(), ())

    def test_the_question_says_what_is_about_to_be_lost_and_where(self):
        with self.assertLogs("colophon", level="INFO") as captured:
            self.main(["--reset-record"], answer="y\n")

        line = "\n".join(captured.output)
        self.assertIn(str(self.path), line)
        self.assertIn("author", line)

    def test_anything_but_yes_leaves_the_record_alone(self):
        for answer in ("n\n", "\n", "yes please\n"):
            with self.subTest(answer=answer):
                self.assertEqual(self.main(["--reset-record"], answer=answer), 1)
                self.assertNotEqual(self.names(), ())

    def test_nothing_to_read_is_a_no(self):
        """A container with no terminal is not a person saying yes."""
        code = self.main(["--reset-record"], answer="")

        self.assertEqual(code, 1)
        self.assertNotEqual(self.names(), ())

    def test_an_empty_record_says_so_rather_than_pretending(self):
        self.main(["--reset-record", "--yes"])

        with self.assertLogs("colophon", level="INFO") as captured:
            code = self.main(["--reset-record", "--yes"])

        self.assertEqual(code, 0)
        self.assertIn("nothing to reset", "\n".join(captured.output))

    def test_an_unknown_argument_is_refused_rather_than_ignored(self):
        """A typo in a command line must not silently start the relay instead."""
        with self.assertLogs("colophon", level="ERROR"):
            code = self.main(["--reset"], answer="y\n")

        self.assertEqual(code, 2)
        self.assertNotEqual(self.names(), ())

    def test_it_does_not_start_the_relay(self):
        """A reset is the whole job; scanning folders afterwards is not wanted."""
        code = self.main(["--reset-record", "--yes"])

        self.assertEqual(code, 0)
        self.assertFalse((self.root / "ingest").exists())


class _Input:
    """Stands in for `sys.stdin`, so a test can answer the question."""

    def __init__(self, text):
        self._text = text

    def readline(self):
        if not self._text:
            return ""
        line, _, rest = self._text.partition("\n")
        self._text = rest
        return line + "\n"

    def isatty(self):
        return False


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
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
            # The default lives in `/backups`, which is the container's own
            # folder; a test that let it default would try to make that path.
            "COLOPHON_RECORD_PATH": str(self.root / "record.db"),
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
