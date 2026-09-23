"""Tests for the Google Books source: what it asks, and what it makes of a reply.

Every reply here is a real recording from Google Books, replayed, so the suite
needs no key and never touches the network. See
`fixtures/googlebooks/README.md` for what each one is and which query made it.
"""

import json
import unittest
import urllib.parse
from pathlib import Path

from colophon.epub import read as read_epub
from colophon.googlebooks import GoogleBooks
from colophon.matching import FileBook, score_candidate
from colophon.sources import SourceError
from tests.tempdir import TemporaryDirectory

RECORDED = Path(__file__).parent / "fixtures" / "googlebooks"
# The cases a ticket rests on rather than the API's own words: never re-recorded,
# and each named in `fixtures/googlebooks/hand-made/README.md`. See the rule in
# `RECORDED`'s own README.
HAND_MADE = RECORDED / "hand-made"
EPUBS = Path(__file__).parent / "fixtures" / "books"

# The Gutenberg book the Poe recordings were made about, as the corrector reads
# it. The tie is a fact about a real file against a real reply, so it is measured
# against the real book rather than against a hand-written stand-in.
_GUTENBERG = read_epub(EPUBS / "the-masque-of-the-red-death-epub3.epub")
FILE_BOOK = FileBook(
    _GUTENBERG.title, _GUTENBERG.authors, _GUTENBERG.language, _GUTENBERG.date
)

KEY = "google-books-key-that-must-never-be-logged"

CRAGSIDE = "9781521748831"
# A well-formed ISBN that is no book's: Google answers 200 and no items.
NO_SUCH_BOOK = "9789999999991"
# The right ISBN with its check digit wrong. Google answers with Cragside
# anyway, carrying the *correct* ISBN, which is why the client verifies.
ONE_DIGIT_OFF = "9781521748830"
UNRELATED = "9780000000000"


class Replay:
    """Stands in for the network: hands back a recorded reply, remembers the URL.

    Each source answers from its own fixtures; this one reads Google's. `folder`
    is for the frozen cases, which live beside the live recordings rather than
    among them.
    """

    def __init__(self, name="by-title-cragside.json", status=200, folder=RECORDED):
        self.body = (folder / name).read_bytes()
        self.status = status
        self.sent = None

    def __call__(self, url, headers):
        self.sent = {"url": url, "headers": headers}
        return self.status, self.body


class ReplayByQuery:
    """Answers from the recording whose query this request actually asked.

    The Gutenberg book is looked up by title, and the reply depends entirely on
    what was asked: a recording replayed for the wrong query would be a test
    that proves nothing. This picks the fixture by matching the request against
    the query each recording was made with, so the test fails loudly rather than
    reading the wrong file if the client ever changes what it sends.
    """

    def __init__(self, **by_query):
        self.by_query = by_query
        self.sent = None
        self.asked = None

    def __call__(self, url, headers):
        self.sent = {"url": url, "headers": headers}
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
        self.asked = query
        for wanted, name in self.by_query.items():
            if wanted in query:
                return 200, (RECORDED / name).read_bytes()
        raise AssertionError(f"no recording for {query!r}; add one to the fixtures")


class LookupByIsbnTests(unittest.TestCase):
    def source(self, replay=None):
        return GoogleBooks(KEY, transport=replay or Replay())

    def test_it_finds_the_book_by_isbn_and_reads_what_the_source_says(self):
        book = self.source().by_isbn(CRAGSIDE)

        self.assertEqual(book.source, "google_books")
        self.assertEqual(book.title, "Cragside")
        self.assertEqual(book.authors, ("L. J. Ross",))
        self.assertEqual(book.language, "en")
        self.assertEqual(book.isbn, CRAGSIDE)

    def test_a_book_google_has_no_edition_for_is_not_a_match(self):
        """A 200 with no items is the ordinary not-found reply, not an error."""
        source = self.source(Replay("by-isbn-no-edition.json"))

        self.assertIsNone(source.by_isbn(NO_SUCH_BOOK))

    def test_an_isbn_one_digit_off_is_not_a_match(self):
        """Google answers with Cragside carrying the *correct* ISBN.

        The reply is a 200 and looks like a match; it is not one, because no
        volume in it carries the ISBN that was asked about.
        """
        source = self.source(Replay("by-isbn-one-digit-off.json"))

        self.assertIsNone(source.by_isbn(ONE_DIGIT_OFF))

    def test_a_reply_of_books_carrying_other_isbns_is_not_a_match(self):
        source = self.source(Replay("by-isbn-unrelated.json"))

        self.assertIsNone(source.by_isbn(UNRELATED))

    def test_it_checks_both_the_ten_and_the_thirteen_digit_identifier(self):
        """The file may carry either form of the same ISBN."""
        replay = Replay()
        source = self.source(replay)

        self.assertIsNotNone(source.by_isbn("1521748837"), "the ISBN-10 on the record")

    def test_it_asks_google_for_the_isbn_it_was_given(self):
        replay = Replay()

        self.source(replay).by_isbn(CRAGSIDE)

        self.assertIn("q=isbn%3A" + CRAGSIDE, replay.sent["url"])

    def test_the_key_travels_in_the_query_as_google_requires(self):
        replay = Replay()

        self.source(replay).by_isbn(CRAGSIDE)

        self.assertIn("key=" + KEY, replay.sent["url"])
        self.assertNotIn("Authorization", replay.sent["headers"])


class LookupByTitleTests(unittest.TestCase):
    def source(self, replay=None):
        return GoogleBooks(KEY, transport=replay or Replay("by-title-cragside.json"))

    def test_it_finds_a_book_by_its_title_and_author(self):
        candidates = self.source().by_title(["Cragside"], "en", "L. J. Ross")

        self.assertEqual(candidates[0].source, "google_books")
        self.assertEqual(candidates[0].title, "Cragside")
        self.assertEqual(candidates[0].authors, ("L. J. Ross",))

    def test_every_volume_in_the_reply_is_offered(self):
        """Each volume is an edition, and choosing between them is the caller's job."""
        candidates = self.source().by_title(["Cragside"], "en", "L. J. Ross")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(len({candidate.isbn for candidate in candidates}), 2)

    def test_it_asks_about_every_form_of_the_title(self):
        replay = Replay("by-title-cragside.json")

        self.source(replay).by_title(
            ["Cragside", "Cragside: A DCI Ryan Mystery"], "en", "L. J. Ross"
        )

        # Both forms go in one request, and both are quoted search terms.
        self.assertIn("q=intitle", replay.sent["url"])

    def test_the_author_is_sent_as_the_filter_that_works(self):
        """`inauthor` narrowed a 300-item reply to the two right volumes."""
        replay = Replay("by-title-cragside.json")

        self.source(replay).by_title(["Cragside"], "en", "L. J. Ross")

        self.assertIn("inauthor", replay.sent["url"])
        self.assertIn("L.+J.+Ross", replay.sent["url"])

    def test_the_files_language_is_sent_as_a_restriction(self):
        replay = Replay("by-title-cragside.json")

        self.source(replay).by_title(["Cragside"], "en", "L. J. Ross")

        self.assertIn("langRestrict=en", replay.sent["url"])

    def test_a_book_with_no_language_is_asked_about_without_a_restriction(self):
        replay = Replay("by-title-cragside.json")

        self.source(replay).by_title(["Cragside"], None, "L. J. Ross")

        self.assertNotIn("langRestrict", replay.sent["url"])

    def test_a_book_with_no_author_is_asked_about_without_the_author_filter(self):
        replay = Replay("by-title-cragside.json")

        self.source(replay).by_title(["Cragside"], "en")

        self.assertNotIn("inauthor", replay.sent["url"])

    def test_a_reply_with_nothing_in_it_offers_nothing(self):
        source = self.source(Replay("by-title-nothing.json"))

        self.assertEqual(source.by_title(["Nobody's Book"], "en", "Nobody At All"), [])

    def test_two_books_of_the_same_name_are_told_apart_by_their_author(self):
        """The lookalike: L. J. Ross's book and Carly Reagon's are not one book."""
        ross = self.source(Replay("by-title-the-infirmary.json")).by_title(
            ["The Infirmary"], "en", "L. J. Ross"
        )
        reagon = self.source(Replay("by-title-the-infirmary-reagon.json")).by_title(
            ["The Infirmary"], "en", "Carly Reagon"
        )

        self.assertEqual(ross[0].authors, ("L. J. Ross",))
        self.assertEqual(reagon[0].authors, ("Carly Reagon",))

    def test_an_empty_title_is_not_asked_about(self):
        replay = Replay("by-title-cragside.json")

        self.assertEqual(self.source(replay).by_title([], "en", "L. J. Ross"), [])
        self.assertIsNone(replay.sent, "no request is made with nothing to ask")


class NoSeriesTests(unittest.TestCase):
    """Google Books has no series data, so nothing may be invented for it."""

    def test_a_google_record_carries_no_series(self):
        book = GoogleBooks(KEY, transport=Replay()).by_isbn(CRAGSIDE)

        self.assertIsNone(book.series)
        self.assertIsNone(book.series_number)

    def test_a_title_reply_carries_no_series_either(self):
        candidates = GoogleBooks(
            KEY, transport=Replay("by-title-cragside.json")
        ).by_title(["Cragside"], "en", "L. J. Ross")

        for candidate in candidates:
            self.assertIsNone(candidate.series)
            self.assertIsNone(candidate.series_number)


class FromSecretFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_key_file_gives_it_a_source(self):
        (self.folder / "key").write_text("a-key\n", encoding="utf-8")

        source = GoogleBooks.from_secret_file(self.folder / "key")

        self.assertIsNotNone(source)

    def test_no_key_file_means_no_source(self):
        self.assertIsNone(GoogleBooks.from_secret_file(self.folder / "missing"))

    def test_an_empty_key_file_means_no_source(self):
        """The file being there but blank is the same as not setting it up."""
        (self.folder / "key").write_text("   \n", encoding="utf-8")

        self.assertIsNone(GoogleBooks.from_secret_file(self.folder / "key"))

    def test_an_unreadable_key_file_is_reported_rather_than_raised(self):
        (self.folder / "key").mkdir()

        with self.assertRaises(SourceError):
            GoogleBooks.from_secret_file(self.folder / "key")


class WhenGoogleRefusesTests(unittest.TestCase):
    """Google answers 400 for a great many things that are not the key's fault."""

    def source(self, name="error-key-rejected.json", status=400):
        return GoogleBooks(KEY, transport=Replay(name, status=status))

    def test_a_key_google_will_not_accept_is_reported_as_a_rejected_key(self):
        with self.assertRaises(SourceError) as caught:
            self.source().by_isbn(CRAGSIDE)

        self.assertTrue(caught.exception.rejected)
        self.assertIn("key", str(caught.exception).lower())

    def test_a_query_of_our_own_that_is_wrong_is_not_a_rejected_key(self):
        """`reason: required` is our bug, not a key the user has to go and fix."""
        source = self.source("error-missing-query.json")

        with self.assertRaises(SourceError) as caught:
            source.by_isbn(CRAGSIDE)

        self.assertFalse(caught.exception.rejected)

    def test_a_parameter_we_got_wrong_is_not_a_rejected_key(self):
        source = self.source("error-max-results-too-high.json")

        with self.assertRaises(SourceError) as caught:
            source.by_isbn(CRAGSIDE)

        self.assertFalse(caught.exception.rejected)

    def test_a_spent_quota_is_not_a_rejected_key(self):
        """It resets, so it is a source that is temporarily unavailable."""
        with self.assertRaises(SourceError) as caught:
            self.source("error-key-rejected.json", status=429).by_isbn(CRAGSIDE)

        self.assertFalse(caught.exception.rejected, "a 429 is not a key problem")
        self.assertIn("429", str(caught.exception))

    def test_a_server_error_is_reported(self):
        with self.assertRaises(SourceError) as caught:
            self.source(status=503).by_isbn(CRAGSIDE)

        self.assertFalse(caught.exception.rejected)
        self.assertIn("503", str(caught.exception))

    def test_a_reply_that_is_not_json_is_reported(self):
        source = GoogleBooks(
            KEY, transport=lambda url, headers: (200, b"<html>nope</html>")
        )

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_a_failure_never_puts_the_key_in_the_message(self):
        for name, status in (
            ("error-key-rejected.json", 400),
            ("error-missing-query.json", 400),
            ("error-key-rejected.json", 429),
            ("error-key-rejected.json", 503),
        ):
            with self.subTest(name=name, status=status):
                source = GoogleBooks(KEY, transport=Replay(name, status=status))

                with self.assertRaises(SourceError) as caught:
                    source.by_isbn(CRAGSIDE)

                self.assertNotIn(KEY, str(caught.exception))

    def test_a_transport_that_blows_up_is_reported_without_the_key(self):
        def refuse(url, headers):
            raise OSError(f"connection reset for {url}")

        source = GoogleBooks(KEY, transport=refuse)

        with self.assertRaises(SourceError) as caught:
            source.by_isbn(CRAGSIDE)

        self.assertNotIn(KEY, str(caught.exception))
        self.assertIn("[key]", str(caught.exception))


class TheOtherFieldsTests(unittest.TestCase):
    """What CBO-38's rules write, as far as Google Books has it.

    The reply is the Cragside title search recorded with the mask the client
    sends today: CBO-37's fields plus `description`, `publishedDate`,
    `publisher` and `imageLinks`. It holds two editions of the book, and one of
    them carries a blurb and a cover while the other does not - which is what
    Google actually answers, and the reason a rule cannot assume a field is
    there.
    """

    def source(self, name="by-title-cragside-other-fields.json"):
        return GoogleBooks(KEY, transport=Replay(name))

    def candidates(self):
        """Both editions the recording holds, so a test does not depend on order."""
        return self.source().by_title(["Cragside"], "en", "L. J. Ross")

    def one(self, isbn):
        """The candidate carrying this ISBN, whichever order Google sent them in."""
        return next(book for book in self.candidates() if book.isbn == isbn)

    def test_it_asks_google_for_the_fields_the_rules_can_write(self):
        replay = Replay("by-title-cragside-other-fields.json")

        GoogleBooks(KEY, transport=replay).by_title(["Cragside"], "en", "L. J. Ross")
        asked = urllib.parse.parse_qs(urllib.parse.urlparse(replay.sent["url"]).query)[
            "fields"
        ][0]

        for field in ("description", "publishedDate", "publisher", "imageLinks"):
            with self.subTest(field=field):
                self.assertIn(field, asked)

    def test_a_candidate_carries_the_blurb_the_source_gave(self):
        blurb = self.one("9781521748831")

        self.assertTrue(blurb.description.startswith("FROM THE #1 INTERNATIONAL"))
        self.assertIn("Cragside", blurb.description)

    def test_the_description_is_the_source_s_own_words_character_for_character(self):
        """Never rewritten, never generated: the recording's own string."""
        recorded = json.loads(
            (RECORDED / "by-title-cragside-other-fields.json").read_text(
                encoding="utf-8"
            )
        )
        expected = next(
            item["volumeInfo"]["description"]
            for item in recorded["items"]
            if (item["volumeInfo"].get("description") or "").startswith("FROM THE")
        )

        self.assertEqual(self.one("9781521748831").description, expected)

    def test_a_candidate_carries_the_publication_date(self):
        self.assertEqual(self.one("9781521748831").date, "2017-07-07")
        self.assertEqual(self.one("9781444846577").date, "2021-03")

    def test_a_candidate_carries_the_publisher_when_the_source_has_one(self):
        self.assertEqual(
            self.one("9781444846577").publisher, "Ulverscroft Special Collection"
        )
        self.assertIsNone(
            self.one("9781521748831").publisher,
            "Google has none for this edition, and none is invented",
        )

    def test_a_candidate_carries_the_cover_the_source_offers(self):
        self.assertEqual(
            self.one("9781444846577").cover,
            "http://books.google.com/books/content?id=7kMMzgEACAAJ"
            "&printsec=frontcover&img=1&zoom=1&source=gbs_api",
        )

    def test_a_volume_with_no_cover_offers_none(self):
        self.assertIsNone(self.one("9781521748831").cover)

    def test_the_isbn_lookup_carries_the_same_fields(self):
        """The ISBN path reads the same reply shape, so it fills the same values."""
        source = GoogleBooks(
            KEY, transport=Replay("by-isbn-cragside-other-fields.json")
        )

        book = source.by_isbn(CRAGSIDE)

        self.assertTrue(book.description.startswith("FROM THE #1 INTERNATIONAL"))
        self.assertEqual(book.date, "2017-07-07")
        self.assertIsNone(book.cover)


class GenreTests(unittest.TestCase):
    """Google carries genres as `categories`, which the shipped mask never asked for.

    The recording is the ISBN request with `items/volumeInfo/categories` appended,
    and its one matching volume is the genre; the pre-CBO-37 title recording holds
    both cases in one file: a library subject heading, and a genre.
    """

    def source(self, name="isbn-cragside-categories.json"):
        return GoogleBooks(KEY, transport=Replay(name))

    def test_the_mask_now_asks_for_the_categories(self):
        replay = Replay("isbn-cragside-categories.json")

        GoogleBooks(KEY, transport=replay).by_isbn(CRAGSIDE)
        asked = urllib.parse.parse_qs(urllib.parse.urlparse(replay.sent["url"]).query)[
            "fields"
        ][0]

        self.assertIn("items/volumeInfo/categories", asked)

    def test_a_candidate_carries_the_category_as_a_genre(self):
        book = self.source().by_isbn(CRAGSIDE)

        self.assertEqual(book.genres, (("Murder", "Murder"),))

    def test_a_character_heading_is_carried_too_and_judged_later(self):
        """`Finlay-Ryan, Maxwell (Fictitious character)` is the model's to refuse."""
        candidates = GoogleBooks(
            KEY, transport=Replay("by-title-cragside.json")
        ).by_title(["Cragside"], "en", "L. J. Ross")
        genres = {book.isbn: book.genres for book in candidates}

        self.assertEqual(genres["9781521748831"], (("Murder", "Murder"),), "a genre")
        self.assertEqual(
            genres["9781444846577"],
            (
                (
                    "Finlay-Ryan, Maxwell (Fictitious character)",
                    "Finlay-Ryan, Maxwell (Fictitious character)",
                ),
            ),
            "a subject heading, carried to the model rather than filtered here",
        )

    def test_a_candidate_with_no_categories_carries_no_genres(self):
        """The older recordings were made before the mask asked for any."""
        book = GoogleBooks(
            KEY, transport=Replay("by-isbn-cragside-other-fields.json")
        ).by_isbn(CRAGSIDE)

        self.assertEqual(book.genres, ())


class HandMadeCaseTests(unittest.TestCase):
    """The frozen cases in `hand-made/`, which no re-record may take away.

    `hand-made/poe-core-cases.json` holds the five volumes of the 0.0000 tie
    that CBO-68's §4 finding and CBO-69's whole reproduction rest on. A test
    reads it so the file is guarded rather than only described: deleting a
    volume, or "fixing" `du6sYyygMgIC`'s casing to match the other four, fails
    here instead of quietly removing the case both tickets were raised for.
    """

    def frozen(self):
        return json.loads((HAND_MADE / "poe-core-cases.json").read_text("utf-8"))

    def test_it_holds_the_five_volumes_that_tie_and_not_the_other_five(self):
        payload = self.frozen()

        self.assertEqual(payload["totalItems"], 300, "the reply's own count is kept")
        self.assertEqual(
            [item["id"] for item in payload["items"]],
            [
                "q6T5zQEACAAJ",
                "XcE-EAAAQBAJ",
                "_hSNzQEACAAJ",
                "du6sYyygMgIC",
                "nPByzgEACAAJ",
            ],
        )

    def test_the_casing_cbo_69_reproduces_is_the_one_that_is_frozen(self):
        """Google spells the preposition `Of` here and `of` in the other nine."""
        volume = next(
            item for item in self.frozen()["items"] if item["id"] == "du6sYyygMgIC"
        )

        self.assertEqual(volume["volumeInfo"]["title"], "The Masque Of The Red Death")
        self.assertEqual(volume["volumeInfo"]["publishedDate"], "2013-01-29")

    def test_all_five_still_tie_at_the_top_score_with_a_gap_of_zero(self):
        """The tie is the case; it is what makes the band `medium` rather than `strong`."""
        source = GoogleBooks(
            KEY, transport=Replay("poe-core-cases.json", folder=HAND_MADE)
        )
        candidates = source.by_title(
            ["The Masque of the Red Death"], "en", "Edgar Allan Poe"
        )
        scores = [
            score_candidate(FILE_BOOK, candidate).score for candidate in candidates
        ]

        self.assertEqual(len(scores), 5, "five volumes, five candidates")
        self.assertEqual(set(scores), {scores[0]}, f"not a tie: {scores}")
        self.assertEqual(
            scores[0], 0.9231, "the file carries a year none of the five matches"
        )


if __name__ == "__main__":
    unittest.main()
