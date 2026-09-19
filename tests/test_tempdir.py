"""Tests for the temporary-folder helper the other tests share."""

import unittest
from pathlib import Path

from tests.tempdir import TemporaryDirectory


class TemporaryDirectoryTests(unittest.TestCase):
    def test_the_folder_can_be_written_to(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)

        book = Path(folder.name) / "Cragside.epub"
        book.write_text("a book", encoding="utf-8")

        self.assertEqual(book.read_text(encoding="utf-8"), "a book")

    def test_two_folders_are_never_the_same(self):
        first = TemporaryDirectory()
        second = TemporaryDirectory()
        self.addCleanup(first.cleanup)
        self.addCleanup(second.cleanup)

        self.assertNotEqual(first.name, second.name)

    def test_cleanup_removes_the_folder_and_what_is_in_it(self):
        folder = TemporaryDirectory()
        (Path(folder.name) / "Cragside.epub").write_text("a book", encoding="utf-8")

        folder.cleanup()

        self.assertFalse(Path(folder.name).exists())

    def test_cleanup_can_be_called_twice(self):
        folder = TemporaryDirectory()

        folder.cleanup()
        folder.cleanup()


if __name__ == "__main__":
    unittest.main()
