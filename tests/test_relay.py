"""Tests for the pass-through relay: waiting, moving, duplicates, dry run."""

import logging
import os
import tempfile
import unittest
from pathlib import Path

from colophon.config import Config
from colophon.relay import Relay, RelayError, temp_name


class RelayTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.ingest = root / "ingest"
        self.output = root / "output"
        self.backups = root / "backups"
        self.config = Config(
            ingest_dir=self.ingest,
            output_dir=self.output,
            backup_dir=self.backups,
            dry_run=False,
            stable_checks=2,
        )
        self.relay = Relay(self.config)
        self.relay.prepare()

    def drop(self, name, text="a book", into=None):
        path = (into or self.ingest) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def settle(self, times=2):
        """Run enough scans for a file that is not changing to be delivered."""
        for _ in range(times):
            self.relay.scan_once()


class WaitingForTheCopyToFinishTests(RelayTestCase):
    def test_a_file_is_not_moved_on_the_first_sighting(self):
        self.drop("Cragside.epub")

        self.relay.scan_once()

        self.assertTrue((self.ingest / "Cragside.epub").exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_a_file_that_stops_changing_is_moved(self):
        self.drop("Cragside.epub")

        self.settle()

        self.assertFalse((self.ingest / "Cragside.epub").exists())
        self.assertEqual((self.output / "Cragside.epub").read_text(), "a book")

    def test_a_file_that_is_still_growing_is_left_alone(self):
        path = self.drop("Berwick.epub", "start")

        for _ in range(5):
            self.relay.scan_once()
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("more")

        self.assertTrue(path.exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_the_wait_length_follows_stable_checks(self):
        relay = Relay(
            Config(
                ingest_dir=self.ingest,
                output_dir=self.output,
                backup_dir=self.backups,
                dry_run=False,
                stable_checks=4,
            )
        )
        self.drop("Belsay.epub")

        for _ in range(3):
            relay.scan_once()
        self.assertTrue((self.ingest / "Belsay.epub").exists())

        relay.scan_once()
        self.assertTrue((self.output / "Belsay.epub").exists())


class WhichFilesAreTakenTests(RelayTestCase):
    def test_every_kind_of_file_passes_through(self):
        for name in ["Book.epub", "Book.kepub.epub", "Comic.cbz", "Scan.pdf", "README"]:
            self.drop(name)

        self.settle()

        moved = sorted(path.name for path in self.output.iterdir())
        self.assertEqual(
            moved, ["Book.epub", "Book.kepub.epub", "Comic.cbz", "README", "Scan.pdf"]
        )

    def test_part_finished_downloads_are_skipped(self):
        for name in ["Book.epub.part", "Book.tmp", "Book.epub.!qB", "Book.crdownload"]:
            self.drop(name)

        self.settle(times=4)

        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(len(list(self.ingest.iterdir())), 4)

    def test_skip_suffixes_ignore_capitals(self):
        self.drop("Book.epub.PART")

        self.settle(times=4)

        self.assertEqual(list(self.output.iterdir()), [])

    def test_hidden_files_are_skipped(self):
        self.drop(".DS_Store")
        self.drop(".Book.epub.colophon-tmp")

        self.settle(times=4)

        self.assertEqual(list(self.output.iterdir()), [])

    def test_files_in_subfolders_are_flattened_into_output(self):
        self.drop("Cragside.epub", into=self.ingest / "LJ Ross" / "DCI Ryan")

        self.settle()

        self.assertTrue((self.output / "Cragside.epub").exists())


class MovingTests(RelayTestCase):
    def test_the_file_is_copied_rather_than_renamed_so_it_gets_our_ownership(self):
        source = self.drop("Cragside.epub")
        source_inode = source.stat().st_ino

        self.settle()

        delivered = self.output / "Cragside.epub"
        self.assertNotEqual(delivered.stat().st_ino, source_inode)
        self.assertEqual(delivered.stat().st_uid, os.getuid())
        self.assertEqual(delivered.stat().st_gid, os.getgid())

    def test_the_temporary_name_is_hidden_and_does_not_end_in_a_book_extension(self):
        self.assertEqual(temp_name("Cragside.epub"), ".Cragside.epub.colophon-tmp")

    def test_no_temporary_files_are_left_behind(self):
        self.drop("Cragside.epub")

        self.settle()

        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()), ["Cragside.epub"]
        )

    def test_an_ingest_folder_it_cannot_write_to_is_refused(self):
        """Without write access the original could never be removed after copying."""
        self.ingest.chmod(0o555)
        self.addCleanup(self.ingest.chmod, 0o755)
        if os.access(self.ingest, os.W_OK):
            self.skipTest("this user can write anywhere, so there is nothing to test")

        with self.assertRaises(RelayError):
            Relay(self.config).prepare()

    def test_the_missing_folders_are_created(self):
        self.assertTrue(self.ingest.is_dir())
        self.assertTrue(self.output.is_dir())
        self.assertTrue(self.backups.is_dir())

    def test_a_file_that_vanishes_mid_scan_does_not_stop_the_relay(self):
        going = self.drop("Gone.epub")
        self.drop("Here.epub")

        self.relay.scan_once()
        going.unlink()
        self.relay.scan_once()

        self.assertTrue((self.output / "Here.epub").exists())
        self.assertFalse((self.output / "Gone.epub").exists())


class CollisionTests(RelayTestCase):
    def test_an_identical_file_goes_to_backups_and_output_is_untouched(self):
        (self.output / "Cragside.epub").write_text("a book", encoding="utf-8")
        self.drop("Cragside.epub", "a book")

        self.settle()

        self.assertEqual((self.output / "Cragside.epub").read_text(), "a book")
        self.assertEqual((self.backups / "Cragside.epub").read_text(), "a book")
        self.assertEqual(list(self.ingest.iterdir()), [])

    def test_a_different_file_of_the_same_name_is_numbered(self):
        (self.output / "Cragside.epub").write_text("first", encoding="utf-8")
        self.drop("Cragside.epub", "second")

        self.settle()

        self.assertEqual((self.output / "Cragside.epub").read_text(), "first")
        self.assertEqual((self.output / "Cragside (2).epub").read_text(), "second")

    def test_numbering_keeps_counting(self):
        (self.output / "Cragside.epub").write_text("first", encoding="utf-8")
        (self.output / "Cragside (2).epub").write_text("second", encoding="utf-8")
        self.drop("Cragside.epub", "third")

        self.settle()

        self.assertEqual((self.output / "Cragside (3).epub").read_text(), "third")

    def test_a_name_without_an_extension_is_numbered_too(self):
        (self.output / "README").write_text("first", encoding="utf-8")
        self.drop("README", "second")

        self.settle()

        self.assertEqual((self.output / "README (2)").read_text(), "second")

    def test_a_second_identical_copy_does_not_overwrite_the_backup(self):
        (self.output / "Cragside.epub").write_text("a book", encoding="utf-8")
        (self.backups / "Cragside.epub").write_text("a book", encoding="utf-8")
        self.drop("Cragside.epub", "a book")

        self.settle()

        self.assertEqual((self.backups / "Cragside (2).epub").read_text(), "a book")


class DryRunTests(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.relay = Relay(
            Config(
                ingest_dir=self.ingest,
                output_dir=self.output,
                backup_dir=self.backups,
                dry_run=True,
                stable_checks=2,
            )
        )

    def test_nothing_is_moved(self):
        self.drop("Cragside.epub")

        self.settle(times=6)

        self.assertTrue((self.ingest / "Cragside.epub").exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_the_book_is_logged_once_however_many_scans_run(self):
        self.drop("Cragside.epub")

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle(times=6)

        lines = [line for line in captured.output if "Cragside.epub" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("would move", lines[0])


class LoggingTests(RelayTestCase):
    def test_one_line_per_book(self):
        self.drop("Cragside.epub")
        self.drop("Berwick.epub")

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        self.assertEqual(len(captured.output), 2)
        self.assertTrue(all("moved" in line for line in captured.output))

    def test_a_duplicate_says_so(self):
        (self.output / "Cragside.epub").write_text("a book", encoding="utf-8")
        self.drop("Cragside.epub", "a book")

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        self.assertEqual(len(captured.output), 1)
        self.assertIn("duplicate", captured.output[0])

    def test_a_collision_says_so(self):
        (self.output / "Cragside.epub").write_text("first", encoding="utf-8")
        self.drop("Cragside.epub", "second")

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        self.assertEqual(len(captured.output), 1)
        self.assertIn("collision", captured.output[0])


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
