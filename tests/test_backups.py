"""Tests for the backups folder: originals kept safe, and not kept for ever."""

import os
import time
import unittest
from pathlib import Path

from colophon.backups import Backups
from tests.tempdir import TemporaryDirectory


def age(path, days):
    """Pretend this file was written this many days ago."""
    seconds = days * 24 * 60 * 60
    when = time.time() - seconds
    os.utime(path, (when, when))


class BackupsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "backups"
        self.addCleanup(self._tmp.cleanup)
        self.backups = Backups(self.folder)
        self.backups.prepare()

    def original(self, name="Cragside.epub", text="a book"):
        path = Path(self._tmp.name) / name
        path.write_text(text, encoding="utf-8")
        return path


class KeepingTests(BackupsTestCase):
    def test_it_copies_the_original_rather_than_taking_it(self):
        book = self.original()

        kept = self.backups.keep(book)

        self.assertEqual(kept, self.folder / "Cragside.epub")
        self.assertEqual(kept.read_text(encoding="utf-8"), "a book")
        self.assertTrue(book.exists(), "the original must still be where it was")

    def test_it_never_overwrites_a_backup_that_is_already_there(self):
        self.backups.keep(self.original(text="first"))

        kept = self.backups.keep(self.original(text="second"))

        self.assertEqual(kept, self.folder / "Cragside (2).epub")
        self.assertEqual((self.folder / "Cragside.epub").read_text(encoding="utf-8"), "first")
        self.assertEqual(kept.read_text(encoding="utf-8"), "second")

    def test_a_name_without_an_extension_is_numbered_too(self):
        self.backups.keep(self.original("README", "first"))

        kept = self.backups.keep(self.original("README", "second"))

        self.assertEqual(kept, self.folder / "README (2)")

    def test_it_leaves_no_half_written_file_behind(self):
        self.backups.keep(self.original())

        self.assertEqual([path.name for path in self.folder.iterdir()], ["Cragside.epub"])

    def test_it_makes_the_folder_if_it_is_not_there(self):
        missing = Path(self._tmp.name) / "elsewhere"

        Backups(missing).keep(self.original())

        self.assertTrue((missing / "Cragside.epub").exists())

    def test_it_keeps_a_same_named_backup_of_a_different_book_apart(self):
        self.backups.keep(self.original("Cragside.epub", "first"))
        self.backups.keep(self.original("Berwick.epub", "second"))

        self.assertEqual(
            sorted(path.name for path in self.folder.iterdir()),
            ["Berwick.epub", "Cragside.epub"],
        )


class ExpiringTests(BackupsTestCase):
    def test_it_deletes_a_backup_older_than_the_retention(self):
        old = self.backups.keep(self.original())
        age(old, 31)

        deleted = self.backups.expire()

        self.assertEqual(deleted, (old,))
        self.assertFalse(old.exists())

    def test_it_keeps_a_backup_inside_the_retention(self):
        fresh = self.backups.keep(self.original())
        age(fresh, 29)

        self.assertEqual(self.backups.expire(), ())
        self.assertTrue(fresh.exists())

    def test_the_retention_is_configurable(self):
        week = Backups(self.folder, retention_days=7)
        old = self.backups.keep(self.original("Old.epub"))
        fresh = self.backups.keep(self.original("Fresh.epub"))
        age(old, 8)
        age(fresh, 6)

        deleted = week.expire()

        self.assertEqual(deleted, (old,))
        self.assertTrue(fresh.exists())

    def test_it_deletes_duplicates_copied_in_by_the_relay_just_the_same(self):
        """The relay files identical duplicates here; they expire like anything else."""
        duplicate = self.backups.keep(self.original("Cragside (2).epub", "a book"))
        age(duplicate, 40)

        self.assertEqual(self.backups.expire(), (duplicate,))

    def test_it_reaches_into_subfolders(self):
        nested = self.folder / "2020" / "Cragside.epub"
        nested.parent.mkdir(parents=True)
        nested.write_text("a book", encoding="utf-8")
        age(nested, 45)

        deleted = self.backups.expire()

        self.assertEqual(deleted, (nested,))
        self.assertFalse(nested.exists())
        self.assertFalse(nested.parent.exists(), "the empty folder goes too")

    def test_a_backups_folder_that_is_not_there_yet_is_not_an_error(self):
        self.assertEqual(Backups(Path(self._tmp.name) / "never-made").expire(), ())

    def test_an_empty_backups_folder_is_not_an_error(self):
        self.assertEqual(self.backups.expire(), ())

    def test_it_reports_everything_it_deleted(self):
        for name in ("One.epub", "Two.epub"):
            age(self.backups.keep(self.original(name)), 60)

        deleted = self.backups.expire()

        self.assertEqual(sorted(path.name for path in deleted), ["One.epub", "Two.epub"])
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_it_never_deletes_the_hidden_files_it_shares_the_folder_with(self):
        """The LLM call counter lives here, and clearing the folder is exactly
        how it would disappear - which would hand every restart a fresh limit.
        """
        counter = self.folder / ".colophon-llm.json"
        counter.write_text('{"date": "2020-01-01", "calls": 200}', encoding="utf-8")
        age(counter, 400)
        old = self.backups.keep(self.original("Old.epub"))
        age(old, 400)

        deleted = self.backups.expire()

        self.assertEqual(deleted, (old,), "the counter is not something it cleared")
        self.assertTrue(counter.exists())
        self.assertEqual(
            counter.read_text(encoding="utf-8"), '{"date": "2020-01-01", "calls": 200}'
        )


if __name__ == "__main__":
    unittest.main()
