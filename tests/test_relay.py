"""Tests for the pass-through relay: waiting, moving, duplicates, dry run."""

import logging
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from colophon.backups import Backups
from colophon.config import Config
from colophon.correction import Corrector
from colophon.epub import read
from colophon.files import temp_name
from colophon.googlebooks import GoogleBooks
from colophon.hardcover import Hardcover
from colophon.relay import Relay, RelayError
from tests.opf import calibre_series, epub3_series, subjects
from tests.samplebooks import AS_DOWNLOADED, CRAGSIDE, ISBN, write_epub
from tests.sources import CRAGSIDE_CANDIDATE, NO_COVER_MATCH, FakeSource, no_network
from tests.tempdir import TemporaryDirectory

# The two sources' recorded replies, read by a replay just as a live one would
# be: the empty answer each of them really gave for a title neither has.
HARDCOVER_RECORDED = Path(__file__).parent / "fixtures" / "hardcover"
GOOGLE_RECORDED = Path(__file__).parent / "fixtures" / "googlebooks"


class RelayTestCase(unittest.TestCase):
    def setUp(self):
        self._refuse_the_network()
        self._tmp = TemporaryDirectory()
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

    def _refuse_the_network(self):
        """Make an outbound HTTP request fail, so no test can quietly make one.

        The relay is the pass that fetches covers, so this is where an
        accidental fetch would show up: a test that reaches the network is a
        test that passes or fails depending on whether the network is there.
        Nothing here means to fetch anything, and the one place that could is
        given a cover by hand.
        """
        import urllib.error
        import urllib.request

        def refuse(request, *args, **kwargs):
            target = getattr(request, "full_url", request)
            raise urllib.error.URLError(
                f"a test tried to reach {target} over the network"
            )

        for module in (urllib.request,):
            patcher = mock.patch.object(module, "urlopen", refuse)
            patcher.start()
            self.addCleanup(patcher.stop)
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
    @unittest.skipUnless(hasattr(os, "getuid"), "no file ownership on this platform")
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


class StuckFileTests(RelayTestCase):
    """A book that copies out fine but cannot be removed from the ingest folder.

    Without care this looks like a brand new book on the very next scan, and
    because output now holds an identical copy it is filed as a duplicate,
    again and again, filling the backups folder with (2), (3), (4)...
    """

    def settle_with_a_file_that_will_not_delete(self, times=8):
        def refuse(self, *args, **kwargs):
            raise PermissionError(13, "Permission denied")

        with (
            mock.patch.object(Path, "unlink", refuse),
            self.assertLogs("colophon", level="INFO") as captured,
        ):
            self.settle(times=times)
        return captured

    def test_it_is_not_copied_out_over_and_over(self):
        self.drop("Cragside.epub")

        self.settle_with_a_file_that_will_not_delete()

        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()), ["Cragside.epub"]
        )
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_the_problem_is_reported_once_not_on_every_scan(self):
        self.drop("Cragside.epub")

        captured = self.settle_with_a_file_that_will_not_delete()

        complaints = [line for line in captured.output if "could not remove" in line]
        self.assertEqual(len(complaints), 1)
        self.assertIn("Cragside.epub", complaints[0])

    def test_the_book_is_still_reported_as_delivered(self):
        self.drop("Cragside.epub")

        captured = self.settle_with_a_file_that_will_not_delete()

        deliveries = [line for line in captured.output if "moved" in line]
        self.assertEqual(len(deliveries), 1)

    def test_it_is_tried_again_once_the_file_changes(self):
        book = self.drop("Cragside.epub", "first")
        self.settle_with_a_file_that_will_not_delete()

        book.write_text("second", encoding="utf-8")
        self.settle()

        self.assertFalse(book.exists())
        self.assertEqual((self.output / "Cragside (2).epub").read_text(), "second")


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


class CorrectingBooksOnTheWayThroughTests(RelayTestCase):
    """A book carrying an ISBN is corrected before it reaches the output folder."""

    def setUp(self):
        super().setUp()
        self.source = FakeSource()
        self.relay = Relay(
            self.config,
            corrector=Corrector(
                sources=[self.source],
                backups=Backups(self.backups),
                dry_run=False,
                # Nothing in this class is about covers, and a relay test that
                # fetched one over the network would be a relay test that fails
                # when the network does.
                fetch=no_network,
            ),
        )

    def drop_a_book(self):
        return write_epub(self.ingest / "Cragside.epub", AS_DOWNLOADED, version="2.0")

    def backups_kept(self):
        return sorted(path.name for path in self.backups.iterdir())

    def test_the_book_that_reaches_output_carries_the_corrected_metadata(self):
        self.drop_a_book()

        self.settle()

        delivered = self.output / "Cragside.epub"
        book = read(delivered)
        self.assertEqual(book.title, "Cragside")
        self.assertEqual(book.authors, ("L.J. Ross",))
        self.assertEqual(calibre_series(delivered), ("DCI Ryan Mysteries", "6"))
        self.assertEqual(epub3_series(delivered), ("DCI Ryan Mysteries", "series", "6"))

    def test_the_line_names_the_long_fields_without_writing_their_values_out(self):
        """The blurb is a thousand characters; the line stays one line.

        The line's job is which fields moved and who supplied them. A blurb
        written into it in full would bury the match and the confidence it is
        there to report.
        """
        write_epub(
            self.ingest / "Cragside.epub",
            f"""    <dc:title>Something Else Entirely</dc:title>
    <dc:creator>Nobody</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
""",
            version="2.0",
        )

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        line = "\n".join(captured.output)
        self.assertIn("description<-hardcover", line)
        self.assertNotIn("FROM THE #1", line, "the blurb itself is in the book, not the log")
        self.assertIn('publisher="Independently Published"<-hardcover', line)
        self.assertIn('date="2017-07-07"<-hardcover', line)
        self.assertLess(max(len(part) for part in captured.output), 1000)

    def test_the_source_never_asked_is_credited_for_nothing(self):
        """Colophon's own writes are attributed to Colophon, not to a source.

        A book nobody matched is marked by Colophon, and the line says so. It
        would be a lie of a kind the log is there to prevent if the tag and the
        note were credited to a source that never saw the book.
        """
        write_epub(self.ingest / "Unknown.epub", CRAGSIDE, version="2.0")
        self.source.candidates = []

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        line = "\n".join(captured.output)
        self.assertIn("tag<-colophon", line)
        self.assertIn("marked colophon:unverified", line)
        self.assertNotIn("<-hardcover", line.split("marked")[1].split("]")[0])

    def test_the_original_is_backed_up_before_it_is_changed(self):
        original = self.drop_a_book().read_bytes()

        self.settle()

        self.assertEqual(self.backups_kept(), ["Cragside.epub"])
        self.assertEqual((self.backups / "Cragside.epub").read_bytes(), original)
        self.assertNotEqual((self.output / "Cragside.epub").read_bytes(), original)

    def test_the_single_line_says_the_match_the_confidence_the_fields_and_the_source(self):
        self.drop_a_book()

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        line = "\n".join(captured.output)
        self.assertIn("moved", line)
        self.assertIn("hardcover matched ISBN 9781521748831", line)
        self.assertIn("confidence 1.00", line)
        self.assertIn('title="Cragside"<-hardcover', line)
        self.assertIn('series_number="6"<-hardcover', line)
        self.assertEqual(len(captured.output), 1, "still one line per book")

    def test_the_line_says_when_a_book_was_matched_on_its_title_instead(self):
        """A book with no ISBN is looked up by its title, and the line says so."""
        write_epub(self.ingest / "Cragside.epub", CRAGSIDE, version="2.0")
        self.relay.correction.sources = (
            FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE]),
        )

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        line = "\n".join(captured.output)
        self.assertIn("hardcover matched Cragside by title and author", line)
        self.assertIn("confidence 1.00", line)

    def test_a_re_dropped_book_is_a_duplicate_of_the_one_already_corrected(self):
        original = self.drop_a_book().read_bytes()
        self.settle()

        (self.ingest / "Cragside.epub").write_bytes(original)
        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        self.assertEqual(read(self.output / "Cragside.epub").title, "Cragside")
        self.assertEqual(self.backups_kept(), ["Cragside (2).epub", "Cragside.epub"])
        self.assertEqual(list(self.ingest.iterdir()), [])
        self.assertIn("duplicate", captured.output[0])
        self.assertIn("already kept as a backup", captured.output[0])

    def test_a_stale_backup_is_cleared_out_without_being_asked(self):
        stale = self.backups / "Old.epub"
        stale.write_text("an original from weeks ago", encoding="utf-8")
        long_ago = time.time() - 31 * 24 * 60 * 60
        os.utime(stale, (long_ago, long_ago))

        with self.assertLogs("colophon", level="INFO") as captured:
            self.relay.scan_once()

        self.assertFalse(stale.exists())
        self.assertIn("deleted 1 backup older than 30 days", "\n".join(captured.output))


class CorrectingInDryRunTests(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.source = FakeSource(found=NO_COVER_MATCH)
        self.relay = Relay(
            Config(
                ingest_dir=self.ingest,
                output_dir=self.output,
                backup_dir=self.backups,
                dry_run=True,
                stable_checks=2,
            ),
            corrector=Corrector(
                sources=[self.source],
                backups=Backups(self.backups),
                dry_run=True,
            ),
        )

    def test_it_says_what_it_would_change_and_moves_and_backs_up_nothing(self):
        write_epub(self.ingest / "Cragside.epub", AS_DOWNLOADED, version="2.0")

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle(times=6)

        line = "\n".join(captured.output)
        self.assertIn("would move", line)
        self.assertIn("would change", line)
        self.assertIn('title="Cragside"<-hardcover', line)
        self.assertTrue((self.ingest / "Cragside.epub").exists())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_it_asks_the_source_once_however_many_scans_a_book_sits_there(self):
        write_epub(self.ingest / "Cragside.epub", AS_DOWNLOADED, version="2.0")

        self.settle(times=6)

        self.assertEqual(len(self.source.asked), 1)


class ABookNothingCanMatchTests(RelayTestCase):
    """The unverified path end to end: marked and delivered, not held back.

    A book no source can vouch for still reaches the library, which is the whole
    point of the ticket - so it is the relay, not the correction, that has to be
    shown to deliver it. Nothing here is retried because nothing here is a
    failure: the sources answered, and all they answered was that they do not
    have the book.
    """

    def setUp(self):
        super().setUp()
        self.source = FakeSource(found=None)
        self.relay = Relay(
            self.config,
            corrector=Corrector(
                sources=[self.source],
                backups=Backups(self.backups),
                dry_run=False,
                fetch=no_network,
            ),
        )
        self.path = write_epub(self.ingest / "Unknown.epub", CRAGSIDE, version="2.0")

    def test_it_reaches_output_carrying_both_halves_of_the_mark(self):
        self.settle()

        delivered = self.output / "Unknown.epub"
        self.assertTrue(delivered.exists(), "a book nothing matched still reaches the library")
        self.assertIn("colophon:unverified", subjects(delivered))
        self.assertEqual(
            read(delivered).description,
            "Metadata could not be verified by Colophon.",
        )
        self.assertFalse(self.path.exists(), "and it is not left in the ingest folder")

    def test_the_original_is_kept_before_the_mark_is_written(self):
        original = self.path.read_bytes()

        self.settle()

        self.assertEqual(
            sorted(path.name for path in self.backups.iterdir()), ["Unknown.epub"]
        )
        self.assertEqual((self.backups / "Unknown.epub").read_bytes(), original)

    def test_it_is_delivered_rather_than_held_for_another_attempt(self):
        """A no-match is an answer, so the book goes out on the first quiet scan.

        This is the half of "not retried; this is a final state" the relay can
        show today: the book is delivered and not sat on. There is no retry
        machinery to *not* use yet - CBO-43 builds it - so this cannot pin a
        marked book out of a window that does not exist. What it pins is that a
        marked book is not treated as unfinished.
        """
        self.settle()

        self.assertFalse(self.path.exists(), "delivered on the first stable scan")
        self.assertTrue((self.output / "Unknown.epub").exists())
        self.assertEqual(len(self.source.asked_titles), 1)

        self.settle(times=3)

        self.assertEqual(
            len(self.source.asked_titles), 1, "and never asked again once it has gone"
        )

    def test_the_line_says_the_book_was_marked_as_well_as_what_was_tried(self):
        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        line = "\n".join(captured.output)
        self.assertIn("moved", line)
        self.assertIn("marked colophon:unverified", line)
        self.assertIn("no source among hardcover has an edition called", line)


class ARealNoMatchThroughTheRelayTests(RelayTestCase):
    """The same, driven by the two sources' own recorded empty replies.

    Nothing here is a stand-in: the recordings are what Hardcover and Google
    Books really answered for a title neither of them has, and the client reads
    them the way it reads a live reply.
    """

    def setUp(self):
        super().setUp()

        def replay_hardcover(url, headers, body):
            # The empty answer: no editions at all. It is the same reply for an
            # ISBN nobody has and for a title nobody has, because it is the
            # absence of an edition that is being answered either way - so one
            # recording serves both questions rather than two files of the same
            # thirteen bytes.
            return 200, (HARDCOVER_RECORDED / "nothing-found.json").read_bytes()

        def replay_google(url, headers):
            # The recording CBO-37 made for a title nobody has. CBO-39 was
            # recorded for the same question and answered the same bytes, so the
            # older one is read rather than a second copy kept beside it.
            return 200, (GOOGLE_RECORDED / "by-title-nothing.json").read_bytes()

        self.relay = Relay(
            self.config,
            corrector=Corrector(
                sources=[
                    Hardcover("a-token", transport=replay_hardcover),
                    GoogleBooks("a-key", transport=replay_google),
                ],
                backups=Backups(self.backups),
                dry_run=False,
                fetch=no_network,
            ),
        )

    def test_both_sources_answering_nothing_leaves_a_marked_book_in_output(self):
        write_epub(self.ingest / "Unknown.epub", CRAGSIDE, version="2.0")

        with self.assertLogs("colophon", level="INFO") as captured:
            self.settle()

        delivered = self.output / "Unknown.epub"
        self.assertTrue(delivered.exists())
        self.assertIn("colophon:unverified", subjects(delivered))
        self.assertIn("metadata could not be verified", read(delivered).description.lower())
        self.assertIn("hardcover", "\n".join(captured.output))
        self.assertIn("google_books", "\n".join(captured.output))


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
