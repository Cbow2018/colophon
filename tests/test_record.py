"""The record: the spellings a library settles on, and the matches behind them."""

import os
import sqlite3
import unittest

from colophon.record import (
    AUTHOR,
    BY_NAME,
    SERIES,
    Match,
    Record,
    RecordError,
    book_key,
)
from tests.tempdir import TemporaryDirectory

HARDCOVER = "hardcover"
GOOGLE = "google_books"

# The three rows Hardcover holds for one person, and the two ids for a second.
LJ = "L.J. Ross"
SPACED = "L. J. Ross"
PLAIN = "LJ Ross"
ROSS_ID = 318638
SPACED_ID = 350233
PLAIN_ID = 350235


class RecordTestCase(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = f"{folder.name}/.colophon.db"
        self.record = Record.open(self.path)
        self.addCleanup(self.record.close)

    def resolve(self, names, source=HARDCOVER, identities=(), overrides=None):
        return self.record.resolve(
            AUTHOR, names, source, identities=identities, overrides=overrides
        )

    def spellings(self, names, **kwargs):
        return [found.spelling for found in self.resolve(names, **kwargs)]

    def standard(self, kind, source, key):
        """The standard filed under one key, read straight out of the table.

        The record exposes the whole table through `names()` and nothing per
        key, deliberately: a method that exists only for a test to call is a
        second way into the record that production never takes.
        """
        row = self.record.connection.execute(
            "SELECT standard FROM names WHERE kind = ? AND source = ? AND key = ?",
            (kind, source, key),
        ).fetchone()
        return row["standard"] if row is not None else None

    def held(self, book_key, column):
        """One column of the match recorded for a book, or None if there is none."""
        row = self.record.connection.execute(
            f"SELECT {column} FROM matches WHERE book_key = ?", (book_key,)
        ).fetchone()
        return row[column] if row is not None else None


class FirstSightTests(RecordTestCase):
    def test_a_new_author_keeps_the_spelling_its_source_gave(self):
        self.assertEqual(self.spellings((LJ,)), [LJ])

    def test_nothing_is_written_until_the_book_lands(self):
        """Resolving is a question, not a decision; only saving changes anything."""
        self.resolve((LJ,))

        self.assertEqual(self.record.names(), ())

    def test_saving_files_the_standard_under_the_name(self):
        resolutions = self.resolve((LJ,))
        self.record.save(resolutions)

        self.assertEqual(self.standard(AUTHOR, BY_NAME, "lj ross"), LJ)

    def test_what_the_source_wrote_is_kept_beside_the_standard(self):
        """The standard and the spelling that produced it, kept together.

        Where they differ is what tells a standard apart from the spelling that
        happened to arrive, which is the question a person asks when their
        library says `L.J. Ross` and the book they dropped in said something
        else. The row is not rewritten by the second source — the standard does
        not move — so what the second source wrote is read out of `names()`.
        """
        self.record.save(self.resolve((LJ,)))

        self.record.save(self.resolve((SPACED,), source=GOOGLE))

        rows = {
            (source, key): (standard, seen)
            for _, source, key, standard, seen in self.record.names()
        }
        self.assertEqual(
            rows[(BY_NAME, "lj ross")], (LJ, LJ), "the first spelling, and the standard"
        )
        self.assertEqual(
            self.spellings((SPACED,), source=GOOGLE),
            [LJ],
            "the second source's spelling follows the standard",
        )


class ConsistencyTests(RecordTestCase):
    """The ticket's own acceptance test, and the two ways it can be satisfied."""

    def test_a_name_already_recorded_is_reused_across_sources(self):
        """Hardcover sets `L.J. Ross`; Google Books spells it `L. J. Ross`."""
        self.record.save(self.resolve((LJ,)))

        self.assertEqual(self.spellings((SPACED,), source=GOOGLE), [LJ])

    def test_the_three_hardcover_rows_reach_one_standard_by_name(self):
        """All three spellings normalise to one key, so no config is needed."""
        self.record.save(self.resolve((LJ,), identities=(ROSS_ID,)))

        self.assertEqual(
            self.spellings((SPACED, PLAIN), identities=(SPACED_ID, PLAIN_ID)),
            [LJ, LJ],
        )

    def test_a_second_book_by_a_recorded_author_keeps_its_spelling(self):
        """The standard is the first one; a later source does not move it."""
        self.record.save(self.resolve((LJ,)))

        self.record.save(self.resolve((SPACED,), source=GOOGLE))

        self.assertEqual(self.standard(AUTHOR, BY_NAME, "lj ross"), LJ)


class IdentityTests(RecordTestCase):
    def test_the_sources_own_id_resolves_a_name_never_seen_before(self):
        """One row, two spellings: the id is what knows they are the same."""
        self.record.save(self.resolve((LJ,), identities=(ROSS_ID,)))

        found = self.resolve(("L. J. Ross-Smith",), identities=(ROSS_ID,))

        self.assertEqual([one.spelling for one in found], [LJ])
        self.assertTrue(found[0].by_id, "the id is what answered")

    def test_a_new_id_is_anchored_to_the_standard_it_resolved_to(self):
        """So the next book from that row is an id lookup, not a name one."""
        self.record.save(self.resolve((LJ,), identities=(ROSS_ID,)))

        self.record.save(
            self.resolve((SPACED,), identities=(SPACED_ID,))
        )

        self.assertEqual(self.standard(AUTHOR, HARDCOVER, str(SPACED_ID)), LJ)

    def test_a_name_resolved_by_its_id_is_not_anchored_again(self):
        """It was anchored when it was first seen; a second row would be noise."""
        self.record.save(self.resolve((LJ,), identities=(ROSS_ID,)))

        self.record.save(self.resolve((LJ,), identities=(ROSS_ID,)))

        self.assertEqual(len(self.record.names()), 2, "the name and one id, once each")


class OverrideTests(RecordTestCase):
    def test_an_override_wins_over_a_recorded_standard(self):
        self.record.save(self.resolve((LJ,)))

        self.assertEqual(
            self.spellings((LJ,), overrides={"lj ross": "L J Ross"}), ["L J Ross"]
        )

    def test_an_override_matches_however_the_key_is_spelt(self):
        """The table is keyed by the normalised name, not by the characters."""
        self.record.save(self.resolve((LJ,)))

        for key in ("lj ross", "L.J. Ross", "L. J. Ross", "LJ  Ross"):
            with self.subTest(key=key):
                self.assertEqual(
                    self.spellings((PLAIN,), overrides={key: "L J Ross"}), ["L J Ross"]
                )

    def test_an_override_never_feeds_the_record_a_standard(self):
        """The table is a layer over the record, not a thing that writes to it.

        The author here has never been seen, so nothing stands in the way of the
        override's value becoming the standard — which is exactly the case the
        old test missed by saving a standard first and letting the second write
        hit `ON CONFLICT DO NOTHING`. Nothing is filed at all: not the override's
        value, and not the source's spelling either, because the pass that
        decided this name was the user's and not the record's.
        """
        self.record.save(
            self.resolve((LJ,), identities=(ROSS_ID,), overrides={"lj ross": "L J Ross"})
        )

        self.assertEqual(self.record.names(), ())

    def test_the_record_learns_nothing_from_an_overridden_pass(self):
        """So taking the override back out leaves the next book to set the standard."""
        self.record.save(
            self.resolve((LJ,), identities=(ROSS_ID,), overrides={"lj ross": "L J Ross"})
        )

        self.assertEqual(self.spellings((SPACED,), source=GOOGLE), [SPACED])

    def test_an_override_does_not_stop_the_match_being_recorded(self):
        """The book still arrived; only the spelling was the user's, not the record's."""
        self.record.save(
            self.resolve((LJ,), overrides={"lj ross": "L J Ross"}),
            Match("9781521748831", HARDCOVER, 1.0),
        )

        self.assertEqual(self.held("9781521748831", "source"), HARDCOVER)

    def test_an_override_does_not_overwrite_a_standard_the_record_holds(self):
        """Taking it back out of the config has to restore the spelling."""
        self.record.save(self.resolve((LJ,)))

        self.record.save(self.resolve((LJ,), overrides={"lj ross": "L J Ross"}))

        self.assertEqual(self.standard(AUTHOR, BY_NAME, "lj ross"), LJ)

        self.assertEqual(self.spellings((LJ,)), [LJ], "and out of the config it is back")

    def test_an_override_is_one_hop_and_is_not_followed_again(self):
        """`A -> B` and `B -> C` writes B; a chain is not a thing to guess at."""
        overrides = {"a": "b", "b": "c"}

        self.assertEqual(self.spellings(("A",), overrides=overrides), ["b"])


class BookKeyTests(unittest.TestCase):
    """What a book is recognised by when it is looked up a second time."""

    def test_an_isbn_is_the_key(self):
        self.assertEqual(book_key("9781521748831", "Anything", ("Anyone",)), "9781521748831")

    def test_the_title_and_author_are_the_key_when_there_is_no_isbn(self):
        self.assertEqual(book_key(None, "Cragside", ("L.J. Ross",)), "cragside lj ross")

    def test_two_books_sharing_a_title_under_different_authors_are_two_books(self):
        """Otherwise one overwrites the other, in a store nothing clears.

        Two books called *The Infirmary* really exist — one by L.J. Ross and one
        by Carly Reagon — and a title-only key would make the second match
        replace the first's, silently, for good.
        """
        one = book_key(None, "The Infirmary", ("L.J. Ross",))
        other = book_key(None, "The Infirmary", ("Carly Reagon",))

        self.assertNotEqual(one, other)

    def test_two_books_with_neither_an_isbn_nor_a_title_are_still_two(self):
        """Both fall back to the author, which is all either of them has."""
        self.assertNotEqual(book_key(None, None, ("A",)), book_key(None, None, ("B",)))

    def test_the_key_ignores_how_the_name_or_the_title_is_spelt(self):
        self.assertEqual(
            book_key(None, "J.R.R. Tolkien", ("J. R. R. Tolkien",)),
            book_key(None, "JRR Tolkien", ("JRR Tolkien",)),
        )

    def test_it_is_made_of_what_the_book_has(self):
        """A missing half is not a hole in the middle of the key."""
        self.assertEqual(book_key(None, "Cragside", ()), "cragside")
        self.assertEqual(book_key(None, None, ("L.J. Ross",)), "lj ross")


class MatchTests(RecordTestCase):
    def test_a_book_already_recorded_takes_a_more_confident_match(self):
        self.record.save((), Match("9781521748831", GOOGLE, 0.9))

        self.record.save((), Match("9781521748831", HARDCOVER, 0.95))

        self.assertEqual(self.held("9781521748831", "source"), HARDCOVER)

    def test_a_less_confident_match_does_not_replace_the_one_held(self):
        self.record.save((), Match("9781521748831", HARDCOVER, 0.95))

        self.record.save((), Match("9781521748831", GOOGLE, 0.9))

        self.assertEqual(self.held("9781521748831", "source"), HARDCOVER)

    def test_a_draw_goes_to_the_source_the_user_trusts_more(self):
        self.record.save((), Match("9781521748831", GOOGLE, 0.95), priority=(HARDCOVER, GOOGLE))

        self.record.save(
            (),
            Match("9781521748831", HARDCOVER, 0.95),
            priority=(HARDCOVER, GOOGLE),
        )

        self.assertEqual(self.held("9781521748831", "source"), HARDCOVER)

    def test_a_draw_does_not_promote_a_source_the_user_ranked_lower(self):
        self.record.save((), Match("9781521748831", HARDCOVER, 0.95), priority=(HARDCOVER, GOOGLE))

        self.record.save((), Match("9781521748831", GOOGLE, 0.95), priority=(HARDCOVER, GOOGLE))

        self.assertEqual(self.held("9781521748831", "source"), HARDCOVER)

    def test_the_same_source_looking_again_refreshes_the_record(self):
        """A source is not ranked against itself, so a re-lookup is not a draw."""
        self.record.save((), Match("9781521748831", HARDCOVER, 0.9))

        self.record.save((), Match("9781521748831", HARDCOVER, 0.95))

        self.assertEqual(self.held("9781521748831", "confidence"), 0.95)


class SeriesTests(RecordTestCase):
    def test_a_series_is_kept_the_same_way_an_author_is(self):
        self.record.save(
            self.record.resolve(SERIES, ("DCI Ryan Mysteries",), HARDCOVER)
        )

        found = self.record.resolve(SERIES, ("DCI Ryan mysteries",), GOOGLE)

        self.assertEqual([one.spelling for one in found], ["DCI Ryan Mysteries"])

    def test_the_record_has_nowhere_to_put_a_series_number(self):
        """The one thing it must never work out, refused by the layout itself."""
        columns = {
            row["name"]
            for row in self.record.connection.execute("PRAGMA table_info(names)")
        } | {
            row["name"]
            for row in self.record.connection.execute("PRAGMA table_info(matches)")
        }

        self.assertNotIn("series_number", columns)
        self.assertNotIn("position", columns)


class FileTests(RecordTestCase):
    def test_a_new_file_is_stamped_with_the_schema_it_was_written_to(self):
        version = self.record.connection.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, 2)

    def test_a_record_from_a_newer_colophon_is_refused(self):
        """Reading a newer layout is how a column somebody added gets dropped."""
        self.record.connection.execute("PRAGMA user_version = 99")
        self.record.connection.commit()
        self.record.close()

        with self.assertRaises(RecordError):
            Record.open(self.path)

    def test_the_parent_folder_is_made_if_it_is_missing(self):
        nested = f"{self.path}.d/inner/.colophon.db"

        opened = Record.open(nested)
        self.addCleanup(opened.close)

        self.assertTrue(opened.path.exists())

    def test_a_record_reopened_finds_what_the_last_one_knew(self):
        self.record.save(self.resolve((LJ,)))
        self.record.close()

        reopened = Record.open(self.path)
        self.addCleanup(reopened.close)

        found = reopened.resolve(AUTHOR, (SPACED,), GOOGLE)
        self.assertEqual([one.spelling for one in found], [LJ])

    def test_an_unusable_path_is_a_record_error(self):
        with self.assertRaises(RecordError):
            Record.open(self.path + "/not-a-folder/here.db")


class ResetTests(RecordTestCase):
    def test_a_reset_empties_the_record(self):
        self.record.save(self.resolve((LJ,)), Match("9781521748831", HARDCOVER, 1.0))

        self.record.reset()

        self.assertEqual(self.record.names(), ())
        self.assertEqual(
            self.record.connection.execute("SELECT * FROM matches").fetchall(), []
        )

    def test_the_next_book_starts_a_fresh_standard(self):
        self.record.save(self.resolve((LJ,)))
        self.record.reset()

        self.assertEqual(self.spellings((SPACED,), source=GOOGLE), [SPACED])

    def test_nothing_clears_it_on_its_own(self):
        """Opening and closing a record is not a reason to lose the library's spellings."""
        self.record.save(self.resolve((LJ,)))
        self.record.close()

        reopened = Record.open(self.path)
        self.addCleanup(reopened.close)

        self.assertEqual(reopened.resolve(AUTHOR, (LJ,), HARDCOVER)[0].spelling, LJ)


class GenresTests(RecordTestCase):
    """What a source's genre was judged to mean, and which list it was judged against."""

    ALLOWED = ("Crime", "Mystery")

    def test_nothing_reads_as_nothing(self):
        self.assertIsNone(self.record.mapping(HARDCOVER, "Murder"))

    def test_a_saved_mapping_is_read_back(self):
        self.record.save_genres(((HARDCOVER, "Murder", "Crime", "Murder"),))

        self.assertEqual(self.record.mapping(HARDCOVER, "Murder"), "Crime")

    def test_a_genre_that_does_not_fit_is_stored_as_an_empty_string(self):
        """SQLite does not treat two nulls as equal, so a null could never be keyed."""
        self.record.save_genres(((HARDCOVER, "Fiction", "", "Fiction"),))

        self.assertEqual(self.record.mapping(HARDCOVER, "Fiction"), "")

    def test_the_same_word_from_two_sources_is_two_rows(self):
        self.record.save_genres(
            (
                (HARDCOVER, "Crime", "Crime", "Crime"),
                (GOOGLE, "Crime", "Mystery", "Crime"),
            )
        )

        self.assertEqual(self.record.mapping(HARDCOVER, "Crime"), "Crime")
        self.assertEqual(self.record.mapping(GOOGLE, "Crime"), "Mystery")

    def test_a_fresh_answer_replaces_the_target_and_leaves_the_provenance(self):
        """A null re-asked after a config change has to be able to become a hit."""
        self.record.save_genres(((HARDCOVER, "Murder", "", "True Crime:Murder"),))

        self.record.save_genres(((HARDCOVER, "Murder", "Crime", "Murder"),))

        self.assertEqual(self.record.mapping(HARDCOVER, "Murder"), "Crime")
        self.assertEqual(self.record.genres(), ((HARDCOVER, "Murder", "Crime", "True Crime:Murder"),))

    def test_nothing_but_a_save_writes_a_mapping(self):
        self.assertEqual(self.record.genres(), ())

    def test_a_reset_empties_the_genres_and_the_list(self):
        self.record.save_genres(((HARDCOVER, "Murder", "Crime", "Murder"),))
        self.record.sweep_genres(self.ALLOWED)

        self.record.reset()

        self.assertEqual(self.record.genres(), ())
        self.assertIsNone(self.record.fingerprint())

    def test_a_fresh_record_has_no_fingerprint_and_the_sweep_writes_one(self):
        self.assertIsNone(self.record.fingerprint())

        self.record.sweep_genres(self.ALLOWED)

        self.assertIsNotNone(self.record.fingerprint())

    def test_a_changed_allowed_list_forgets_the_genres_that_did_not_fit(self):
        self.record.sweep_genres(self.ALLOWED)
        self.record.save_genres(
            (
                (HARDCOVER, "Fiction", "", "Fiction"),
                (HARDCOVER, "Murder", "Crime", "Murder"),
            )
        )

        self.record.sweep_genres(("Crime", "Mystery", "True Crime"))

        self.assertIsNone(self.record.mapping(HARDCOVER, "Fiction"), "askable again")
        self.assertEqual(
            self.record.mapping(HARDCOVER, "Murder"),
            "Crime",
            "a positive target is not relative to the list, and is re-validated on read",
        )

    def test_reordering_or_re_casing_the_list_changes_nothing(self):
        self.record.sweep_genres(("Crime", "Mystery"))
        self.record.save_genres(((HARDCOVER, "Fiction", "", "Fiction"),))

        self.record.sweep_genres(("mystery", " CRIME "))

        self.assertEqual(self.record.mapping(HARDCOVER, "Fiction"), "")
        self.assertEqual(self.record.genres(), ((HARDCOVER, "Fiction", "", "Fiction"),))

    def test_the_sweep_is_idempotent(self):
        self.record.sweep_genres(self.ALLOWED)
        held = self.record.fingerprint()

        self.record.sweep_genres(self.ALLOWED)

        self.assertEqual(self.record.fingerprint(), held)

    def test_the_genre_tables_are_the_two_the_note_names(self):
        columns = {
            table: {
                row["name"]
                for row in self.record.connection.execute(f"PRAGMA table_info({table})")
            }
            for table in ("genres", "genre_list")
        }

        self.assertEqual(columns["genres"], {"source", "genre", "mapped", "seen"})
        self.assertEqual(columns["genre_list"], {"id", "fingerprint"})

    def test_the_list_holds_one_row_however_often_it_is_swept(self):
        """Without the CHECK this table accumulates a row per sweep."""
        self.record.sweep_genres(self.ALLOWED)
        self.record.sweep_genres(("Fantasy",))

        rows = self.record.connection.execute("SELECT * FROM genre_list").fetchall()
        self.assertEqual(len(rows), 1)


class VersionOneTests(unittest.TestCase):
    """CBO-41's record, carried forward to the mapping schema CBO-42 needs."""

    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = f"{folder.name}/.colophon.db"

    def version_one(self):
        """A record as CBO-41 wrote it: a `genres` table with one column."""
        connection = sqlite3.connect(self.path)
        connection.executescript(
            "CREATE TABLE names (kind TEXT NOT NULL, source TEXT NOT NULL, "
            "key TEXT NOT NULL, standard TEXT NOT NULL, seen TEXT NOT NULL, "
            "PRIMARY KEY (kind, source, key));"
            "CREATE TABLE matches (book_key TEXT PRIMARY KEY, source TEXT NOT NULL, "
            "confidence REAL NOT NULL, matched_at TEXT NOT NULL, "
            "matched_as TEXT NOT NULL);"
            "CREATE TABLE genres (genre TEXT PRIMARY KEY);"
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        connection.close()

    def test_a_version_one_file_is_carried_forward(self):
        self.version_one()

        record = Record.open(self.path)
        self.addCleanup(record.close)

        version = record.connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 2)
        record.save_genres((("hardcover", "Murder", "Crime", "Murder"),))

        self.assertEqual(record.mapping("hardcover", "Murder"), "Crime")

    def test_the_version_one_genre_table_is_replaced_by_the_mapping_one(self):
        """It held one column and nothing ever wrote a row to it."""
        self.version_one()

        record = Record.open(self.path)
        self.addCleanup(record.close)

        columns = {
            row["name"]
            for row in record.connection.execute("PRAGMA table_info(genres)")
        }
        self.assertEqual(columns, {"source", "genre", "mapped", "seen"})

    def test_what_the_old_record_knew_is_kept(self):
        self.version_one()
        first = Record.open(self.path)
        first.save(first.resolve(AUTHOR, (LJ,), HARDCOVER))
        first.close()

        record = Record.open(self.path)
        self.addCleanup(record.close)

        found = record.resolve(AUTHOR, (SPACED,), GOOGLE)
        self.assertEqual([one.spelling for one in found], [LJ])


class FileNameTests(unittest.TestCase):
    def test_the_record_is_a_single_file(self):
        """Default journal mode, so no `-wal` or `-shm` appears beside it.

        The default lives in the backups folder, where a sibling file would be
        one more thing to keep `Backups.expire()` away from and one more thing to
        explain. One connection and one writer needs nothing more than this, so
        the folder is asserted to hold exactly the record, rather than asserted
        not to hold a name that could not have appeared either way.
        """
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = f"{folder.name}/.colophon.db"

        record = Record.open(path)
        record.save(record.resolve(AUTHOR, (LJ,), HARDCOVER))
        record.close()

        self.assertEqual(sorted(os.listdir(folder.name)), [".colophon.db"])

    def test_the_file_really_is_sqlite(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = f"{folder.name}/.colophon.db"
        record = Record.open(path)
        record.close()

        with open(path, "rb") as handle:
            self.assertEqual(handle.read(16), b"SQLite format 3\x00")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
