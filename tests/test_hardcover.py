"""Tests for the Hardcover source: what it asks for, and what it makes of the reply.

The replies are real recordings from Hardcover's API, replayed here, so the
suite needs no key and never touches the network. See
`fixtures/hardcover/README.md` for what each one is.
"""

import json
import unittest
from pathlib import Path

from colophon import hardcover
from colophon.hardcover import Hardcover
from colophon.sources import SourceError, genre_parts
from tests.tempdir import TemporaryDirectory

RECORDED = Path(__file__).parent / "fixtures" / "hardcover"
# The cases a ticket rests on rather than the API's own words: never re-recorded,
# and each named in `fixtures/hardcover/hand-made/README.md`. See `RECORDED`'s own
# README for the rule.
HAND_MADE = RECORDED / "hand-made"
TOKEN = "hardcover-token-that-must-never-be-logged"

CRAGSIDE = "9781521748831"
NORMAL_PEOPLE = "9780571334650"
MISTBORN = "9780765311788"
THE_HOBBIT = "9780007458424"
# The ISBN the design spec uses for Cragside, which Hardcover has no edition for.
NO_SUCH_BOOK = "9781786813891"
A_HAND_MADE_BOOK = "9780000000003"
A_WIDER_REPLY = "9780000000004"

# The titles the CBO-36 fixture files were recorded against.
CRAGSIDE_TITLE = "Cragside"
BERWICK_TITLE = "Berwick"
BELSAY_TITLE = "Belsay"
THE_INFIRMARY_TITLE = "The Infirmary"


class Replay:
    """Stands in for the network: hands back a recorded reply, remembers the request.

    `folder` is for the two hand-made fixtures, which live beside the live
    recordings rather than among them.
    """

    def __init__(self, name="by-isbn-found.json", status=200, folder=RECORDED):
        self.body = (folder / name).read_bytes()
        self.status = status
        self.sent = None

    def __call__(self, url, headers, body):
        self.sent = {"url": url, "headers": headers, "body": json.loads(body)}
        return self.status, self.body


def answering(status, body):
    return lambda url, headers, request: (status, body)


class LookupTests(unittest.TestCase):
    def source(self, replay=None):
        return Hardcover(TOKEN, transport=replay or Replay())

    def test_it_finds_the_book_by_isbn_and_reads_what_the_source_says(self):
        book = self.source().by_isbn(CRAGSIDE)

        self.assertEqual(book.source, "hardcover")
        self.assertEqual(book.title, "Cragside")
        self.assertEqual(book.authors, ("L.J. Ross",))
        self.assertEqual(book.series, "DCI Ryan Mysteries")
        self.assertEqual(book.series_number, "6")
        self.assertEqual(book.language, "en")
        self.assertEqual(book.isbn, CRAGSIDE)

    def test_an_isbn_no_edition_carries_is_not_a_match(self):
        source = self.source(Replay("nothing-found.json"))

        self.assertIsNone(source.by_isbn(NO_SUCH_BOOK))

    def test_it_carries_the_author_ids_the_record_keys_a_name_by(self):
        """The id is what says two spellings are one row, so it is asked for."""
        book = self.source(Replay("by-isbn-cragside-authors.json")).by_isbn(CRAGSIDE)

        self.assertEqual(book.authors, ("L.J. Ross",))
        self.assertEqual(book.author_ids, (318638,))
        self.assertEqual(book.series_id, 23832)

    def test_a_reply_that_does_not_carry_an_id_leaves_it_empty(self):
        """The pre-CBO-41 recordings have no ids; a missing one is absent, not a bug."""
        book = self.source(Replay("sparse-isbn-reply.json", folder=HAND_MADE)).by_isbn(
            CRAGSIDE
        )

        self.assertEqual(book.authors, ("L.J. Ross",))
        self.assertEqual(book.author_ids, (None,))
        self.assertIsNone(book.series_id)

    def test_the_ids_are_asked_for(self):
        replay = Replay("by-isbn-cragside-authors.json")

        self.source(replay).by_isbn(CRAGSIDE)

        query = replay.sent["body"]["query"]
        self.assertIn("author {", query)
        self.assertIn("id", query)

    def test_it_asks_about_editions_because_books_carry_no_isbn(self):
        replay = Replay()

        self.source(replay).by_isbn(CRAGSIDE)

        query = replay.sent["body"]["query"]
        for wanted in ("editions", "isbn_13", "isbn_10", "book_series", "language"):
            self.assertIn(wanted, query)

    def test_it_asks_for_the_featured_series_first(self):
        replay = Replay()

        self.source(replay).by_isbn(CRAGSIDE)

        query = replay.sent["body"]["query"]
        self.assertIn("featured", query)
        self.assertIn("featured: desc", query)
        self.assertIn("position: asc", query)

    def test_it_does_not_ask_for_the_series_details_it_never_uses(self):
        replay = Replay()

        self.source(replay).by_isbn(CRAGSIDE)

        self.assertNotIn("details", replay.sent["body"]["query"])

    def test_the_isbn_is_sent_as_a_variable_and_not_spliced_into_the_query(self):
        replay = Replay()

        self.source(replay).by_isbn(CRAGSIDE)

        self.assertEqual(replay.sent["body"]["variables"], {"isbn": CRAGSIDE})
        self.assertNotIn(CRAGSIDE, replay.sent["body"]["query"])

    def test_it_takes_the_work_title_rather_than_the_edition_title(self):
        """The Hobbit's edition is called "The Hobbit"; the work is not."""
        source = self.source(Replay("by-isbn-edition-title.json"))

        book = source.by_isbn(THE_HOBBIT)

        self.assertEqual(book.title, "The Hobbit, or There and Back Again")
        self.assertEqual(book.authors, ("J.R.R. Tolkien",))

    def test_it_falls_back_to_the_edition_title_when_the_work_has_none(self):
        source = self.source(Replay("work-without-title.json", folder=HAND_MADE))

        book = source.by_isbn(A_HAND_MADE_BOOK)

        self.assertEqual(book.title, "The Edition Title")
        self.assertEqual(book.language, "fr")

    def test_it_takes_authors_and_leaves_the_translator_behind(self):
        """A reply wider than the question is filtered again, not trusted."""
        source = self.source(Replay("wider-than-the-question.json", folder=HAND_MADE))

        book = source.by_isbn(A_WIDER_REPLY)

        self.assertEqual(book.authors, ("The Author",))

    def test_a_standalone_book_comes_back_with_no_series(self):
        source = self.source(Replay("by-isbn-no-series.json"))

        book = source.by_isbn(NORMAL_PEOPLE)

        self.assertEqual(book.title, "Normal People")
        self.assertEqual(book.authors, ("Sally Rooney",))
        self.assertIsNone(book.series)
        self.assertIsNone(book.series_number)

    def test_it_prefers_the_series_hardcover_marks_as_featured(self):
        """Mistborn is in three series, and only one of them is the book's own.

        The recording has the featured row first and the other two after it, so
        this no longer shows the client correcting a server that puts the featured
        one last — the old recording was made without the query's `order_by` and
        did show that, and the 2026-09-23 re-record proved the claim false. What
        it shows now is that `_series` picks the row carrying `featured` rather
        than simply taking the first.
        """
        source = self.source(Replay("by-isbn-two-series.json"))

        book = source.by_isbn(MISTBORN)

        self.assertEqual(book.series, "The Mistborn Saga: The Original Trilogy")
        self.assertEqual(book.series_number, "1")

    def test_it_names_itself_to_the_source(self):
        replay = Replay()

        self.source(replay).by_isbn(CRAGSIDE)

        self.assertEqual(replay.sent["url"], "https://api.hardcover.app/v1/graphql")
        self.assertIn("Colophon", replay.sent["headers"]["User-Agent"])
        self.assertEqual(replay.sent["headers"]["Content-Type"], "application/json")


class TitleLookupTests(unittest.TestCase):
    """The title path, for a book whose file carries no ISBN.

    The replies are real recordings too; see `fixtures/hardcover/README.md`.
    """

    def source(self, replay=None):
        return Hardcover(TOKEN, transport=replay or Replay("by-title-cragside.json"))

    def test_it_finds_the_book_by_a_cleaned_title(self):
        candidates = self.source().by_title([CRAGSIDE_TITLE], "en")

        self.assertEqual(len(candidates), 1)
        cragside = candidates[0]
        self.assertEqual(cragside.title, "Cragside")
        self.assertEqual(cragside.authors, ("L.J. Ross",))
        self.assertEqual(cragside.series, "DCI Ryan Mysteries")
        self.assertEqual(cragside.series_number, "6")
        self.assertEqual(cragside.language, "en")
        # Read off the edition, which is the only place Hardcover keeps one.
        self.assertEqual(cragside.isbn, CRAGSIDE)

    def test_it_reads_berwick_and_belsay_too(self):
        """Belsay's file carries no series number; Hardcover has #23."""
        berwick = self.source(Replay("by-title-berwick.json")).by_title(
            [BERWICK_TITLE], "en"
        )
        belsay = self.source(Replay("by-title-belsay.json")).by_title(
            [BELSAY_TITLE], "en"
        )

        self.assertEqual(berwick[0].series_number, "24")
        self.assertEqual(belsay[0].title, "Belsay")
        self.assertEqual(belsay[0].series_number, "23")

    def test_one_work_comes_back_once_however_many_editions_it_has(self):
        """Cragside's reply with the same work twice, as the API really sends it."""
        reply = {
            "data": {
                "editions": [
                    {
                        "title": "Cragside",
                        "language": None,
                        "book": {
                            "id": 1198994,
                            "title": "Cragside",
                            "contributions": [
                                {
                                    "contribution": "Author",
                                    "author": {"name": "L.J. Ross"},
                                }
                            ],
                            "book_series": [],
                        },
                    },
                    {
                        "title": "Cragside: A DCI Ryan Mystery",
                        "language": {"code2": "en"},
                        "book": {
                            "id": 1198994,
                            "title": "Cragside",
                            "contributions": [
                                {
                                    "contribution": "Author",
                                    "author": {"name": "L.J. Ross"},
                                }
                            ],
                            "book_series": [],
                        },
                    },
                ]
            }
        }
        source = Hardcover(TOKEN, transport=answering(200, json.dumps(reply).encode()))

        candidates = source.by_title([CRAGSIDE_TITLE], "en")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Cragside")

    def test_a_work_with_no_id_of_its_own_is_not_mistaken_for_another(self):
        """`books.title` is nullable and `id` may be missing from a reply."""
        reply = {
            "data": {
                "editions": [
                    {
                        "title": "Cragside",
                        "language": None,
                        "book": {"title": "Cragside"},
                    },
                    {
                        "title": "Cragside",
                        "language": None,
                        "book": {"title": "Cragside"},
                    },
                ]
            }
        }
        source = Hardcover(TOKEN, transport=answering(200, json.dumps(reply).encode()))

        self.assertEqual(len(source.by_title([CRAGSIDE_TITLE], "en")), 2)

    def test_a_title_is_asked_about_with_in_because_eq_is_case_sensitive(self):
        """`_ilike` is refused by the server, so `_in` on the exact title it is."""
        replay = Replay()

        self.source(replay).by_title([CRAGSIDE_TITLE], "en")

        query = replay.sent["body"]["query"]
        self.assertIn("title: {_in: $titles}", query)
        self.assertNotIn("_ilike", query)
        self.assertNotIn("_eq: $title", query)

    def test_it_asks_only_about_the_language_the_file_is_written_in(self):
        replay = Replay()

        self.source(replay).by_title([CRAGSIDE_TITLE], "en")

        variables = replay.sent["body"]["variables"]
        self.assertEqual(variables["language"], "en")
        self.assertIn("code2: {_eq: $language}", replay.sent["body"]["query"])

    def test_a_three_letter_tag_is_asked_about_on_the_other_column(self):
        """This filter is what keeps another language's editions out."""
        replay = Replay()

        self.source(replay).by_title([CRAGSIDE_TITLE], "eng")

        variables = replay.sent["body"]["variables"]
        self.assertEqual(variables["language"], "eng")
        self.assertIn("code3: {_eq: $language}", replay.sent["body"]["query"])
        self.assertNotIn("code2: {_eq: $language}", replay.sent["body"]["query"])

    def test_a_file_that_names_no_language_is_asked_about_without_one(self):
        """`code2` is not nullable, so asking for a null language is refused."""
        replay = Replay()

        self.source(replay).by_title([CRAGSIDE_TITLE], None)

        variables = replay.sent["body"]["variables"]
        self.assertNotIn("language", variables)
        self.assertNotIn("_eq: $language", replay.sent["body"]["query"])

    def test_it_asks_about_the_work_and_not_the_edition(self):
        replay = Replay()

        self.source(replay).by_title([CRAGSIDE_TITLE], "en")

        query = replay.sent["body"]["query"].replace("\n", " ")
        self.assertIn("book: {title: {_in: $titles}}", query)
        self.assertIn("contributions", query)
        self.assertIn("book_series", query)

    def test_no_titles_means_nothing_is_asked(self):
        replay = Replay()

        self.assertEqual(self.source(replay).by_title([], "en"), [])
        self.assertEqual(self.source(replay).by_title(["  "], "en"), [])
        self.assertIsNone(replay.sent, "an empty question is not worth a request")

    def test_no_work_by_that_title_is_no_candidates(self):
        replay = Replay("nothing-found.json")

        self.assertEqual(self.source(replay).by_title([CRAGSIDE_TITLE], "en"), [])

    def test_a_reply_that_does_not_answer_the_question_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(200, b'{"data":{}}'))

        with self.assertRaises(SourceError):
            source.by_title([CRAGSIDE_TITLE], "en")


class ErrorTests(unittest.TestCase):
    def test_a_rejected_token_is_a_source_problem(self):
        source = Hardcover(
            TOKEN, transport=answering(401, b'{"error":"invalid_token"}')
        )

        with self.assertRaises(SourceError) as caught:
            source.by_isbn(CRAGSIDE)

        self.assertIn("token", str(caught.exception))

    def test_a_token_without_the_right_scope_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(403, b'{"error":"forbidden"}'))

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_rate_limiting_is_a_source_problem(self):
        source = Hardcover(
            TOKEN, transport=answering(429, b'{"error":"Too Many Requests"}')
        )

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_a_server_error_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(500, b"<html>oops</html>"))

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_a_reply_that_is_not_json_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(200, b"not json at all"))

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_graphql_errors_in_the_reply_are_a_source_problem(self):
        source = Hardcover(
            TOKEN, transport=answering(200, b'{"errors":[{"message":"no such field"}]}')
        )

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_a_reply_that_does_not_answer_the_question_is_a_source_problem(self):
        """Better to say we could not ask than to report a book as not found."""
        source = Hardcover(TOKEN, transport=answering(200, b'{"data":{}}'))

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_a_network_failure_is_a_source_problem(self):
        def refuse(url, headers, body):
            raise OSError("connection refused")

        with self.assertRaises(SourceError):
            Hardcover(TOKEN, transport=refuse).by_isbn(CRAGSIDE)

    def test_the_token_never_reaches_the_error_message(self):
        """Even when the failure itself quotes the headers it was given."""

        def echoing(url, headers, body):
            raise OSError(f"could not send {headers}")

        source = Hardcover(TOKEN, transport=echoing)

        with self.assertRaises(SourceError) as caught:
            source.by_isbn(CRAGSIDE)

        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertIn("[token]", str(caught.exception))


class SecretFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def secret(self, text):
        path = self.folder / "hardcover_token"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_token_comes_from_the_secret_file(self):
        replay = Replay()

        source = Hardcover.from_secret_file(self.secret(TOKEN + "\n"), transport=replay)
        source.by_isbn(CRAGSIDE)

        self.assertEqual(replay.sent["headers"]["Authorization"], f"Bearer {TOKEN}")

    def test_a_token_file_that_says_bearer_is_not_doubled_up(self):
        """A token copied whole from Hardcover's settings page carries its own prefix."""
        for prefix in ("Bearer ", "bearer ", "BEARER "):
            with self.subTest(prefix=prefix):
                replay = Replay()

                source = Hardcover.from_secret_file(
                    self.secret(f"{prefix}{TOKEN}\n"), transport=replay
                )
                source.by_isbn(CRAGSIDE)

                self.assertEqual(
                    replay.sent["headers"]["Authorization"], f"Bearer {TOKEN}"
                )

    def test_no_secret_file_means_there_is_no_source(self):
        self.assertIsNone(Hardcover.from_secret_file(self.folder / "hardcover_token"))

    def test_an_empty_secret_file_means_there_is_no_source(self):
        self.assertIsNone(Hardcover.from_secret_file(self.secret("   \n")))

    def test_a_secret_file_that_cannot_be_read_is_a_source_problem(self):
        unreadable = self.folder / "hardcover_token"
        unreadable.mkdir()

        with self.assertRaises(SourceError):
            Hardcover.from_secret_file(unreadable)


class TheOtherFieldsTests(unittest.TestCase):
    """What CBO-38's rules write, from the fields Hardcover really keeps.

    The blurb and the release date live on the work; the publisher, the language
    and the ISBN live on the edition. A candidate is built from both, so it has
    to reach across. The reply is the real one for the Cragside edition.
    """

    def source(self, name="by-isbn-cragside-edition.json"):
        return Hardcover(TOKEN, transport=Replay(name))

    def test_it_asks_for_the_fields_the_rules_can_write(self):
        replay = Replay()

        Hardcover(TOKEN, transport=replay).by_isbn(CRAGSIDE)

        query = replay.sent["body"]["query"]
        for wanted in ("description", "publisher", "release_date", "image"):
            with self.subTest(field=wanted):
                self.assertIn(wanted, query)

    def test_a_candidate_carries_the_blurb_the_work_has(self):
        book = self.source().by_isbn(CRAGSIDE)

        self.assertTrue(book.description.startswith("FROM THE #1 INTERNATIONAL"))
        self.assertIn("Cragside", book.description)

    def test_the_description_is_the_source_s_own_words_character_for_character(self):
        recorded = json.loads(
            (RECORDED / "by-isbn-cragside-edition.json").read_text(encoding="utf-8")
        )
        expected = recorded["data"]["editions"][0]["book"]["description"]

        self.assertEqual(self.source().by_isbn(CRAGSIDE).description, expected)

    def test_a_candidate_carries_the_publisher_and_the_date(self):
        book = self.source().by_isbn(CRAGSIDE)

        self.assertEqual(book.publisher, "Independently Published")
        self.assertEqual(book.date, "2017-07-07")

    def test_a_candidate_carries_the_cover_the_source_offers(self):
        book = self.source().by_isbn(CRAGSIDE)

        self.assertEqual(
            book.cover,
            "https://assets.hardcover.app/external_data/40810017/"
            "88c4da5caf5a76472600888c8c4ada978965ebdd.jpeg",
        )

    def test_a_book_with_no_publisher_or_cover_carries_neither(self):
        """Hardcover had neither for Normal People, and neither was invented.

        The reply showing that is the pre-CBO-38 one, kept in `hand-made/`: a
        re-record gives the book a publisher and a cover, which is the answer to
        CBO-38 and the end of this case.
        """
        book = self.source(Replay("sparse-isbn-reply.json", folder=HAND_MADE)).by_isbn(
            NORMAL_PEOPLE
        )

        self.assertIsNone(book.publisher)
        self.assertIsNone(book.cover)

    def test_the_title_path_carries_them_too(self):
        candidates = self.source(
            Replay("cbo-38-without-tags.json", folder=HAND_MADE)
        ).by_title([CRAGSIDE_TITLE], "en")

        self.assertTrue(
            candidates[0].description.startswith("FROM THE #1 INTERNATIONAL")
        )
        self.assertEqual(candidates[0].publisher, "Independently Published")
        self.assertTrue(candidates[0].cover.startswith("https://assets.hardcover.app/"))


class GenreTests(unittest.TestCase):
    """What CBO-42 reads: the community tags Hardcover files under `Genre`.

    Every pair is `(genre, the source's own string it came out of)`: the genre is
    what is asked about and cached, and the string is the provenance the cache
    keeps. `cached_tags` holds four categories and only `Genre` is a genre.
    """

    CRAGSIDE_GENRES = "9781521748831"
    THE_INFIRMARY_GENRES = "9781799729945"
    PYRAMIDS = "9780575064843"
    THE_TRIAL = "9781529196382"
    NO_EDITION = "9781473225374"

    def source(self, name):
        return Hardcover(TOKEN, transport=Replay(name))

    def test_a_candidate_carries_the_genres_the_source_holds(self):
        book = self.source("by-isbn-9781521748831-genres.json").by_isbn(
            self.CRAGSIDE_GENRES
        )

        self.assertEqual(
            book.genres,
            (
                ("Murder", "Murder"),
                ("Crime", "Crime"),
                ("Thriller", "Thriller"),
                ("Mystery", "Mystery"),
            ),
        )

    def test_only_the_genre_category_is_read(self):
        """`Mood` and `Content Warning` are the same shape and are not genres."""
        book = self.source("by-isbn-9781521748831-genres.json").by_isbn(
            self.CRAGSIDE_GENRES
        )

        for _, written in book.genres:
            with self.subTest(written=written):
                self.assertNotIn(written, ("dark", "fast-paced"))

    def test_a_second_book_of_the_same_kind_adds_only_its_new_genre(self):
        """*The Infirmary*'s `Suspense` is the fifth spelling of one shelf label.

        `Thriller`, `Crime` and `Mystery` are *Cragside*'s too; `Suspense` is the
        one genre this book brings that the other did not, which is the whole
        complaint the ticket exists for.
        """
        book = self.source("by-isbn-9781799729945-genres.json").by_isbn(
            self.THE_INFIRMARY_GENRES
        )

        self.assertEqual(
            book.genres,
            (
                ("Thriller", "Thriller"),
                ("Crime", "Crime"),
                ("Suspense", "Suspense"),
                ("Mystery", "Mystery"),
            ),
        )

    def test_a_packed_genre_is_two_genres_keeping_the_string_they_came_from(self):
        book = self.source("by-isbn-9781529196382-packed-genres.json").by_isbn(
            self.THE_TRIAL
        )
        genres = dict(book.genres)

        self.assertIn("Crime Fiction", genres, "the leaf is its own genre")
        self.assertEqual(
            genres["Crime Fiction"],
            "Thriller & Suspense:Crime Fiction",
            "and the unsplit string is kept, for the cache's provenance",
        )

    def test_a_genre_split_twice_over_keeps_the_first_string_it_came_from(self):
        """`Fantasy` arrives alone and again inside `Fantasy:Humour`."""
        book = self.source("by-isbn-9780575064843-packed-genres.json").by_isbn(
            self.PYRAMIDS
        )
        genres = [genre for genre, _ in book.genres]

        self.assertEqual(genres.count("Fantasy"), 1, "one genre, one question")
        self.assertIn("Humour", genres, "and the other half of the path is still new")
        self.assertEqual(dict(book.genres)["Fantasy"], "Fantasy")

    def test_the_only_genre_can_be_one_the_model_will_refuse(self):
        """*Berwick*'s single genre is `Fiction`, which is not a shelf label."""
        book = self.source("by-isbn-9781529978940-genres.json").by_isbn("9781529978940")

        self.assertEqual(book.genres, (("Fiction", "Fiction"),))

    def test_a_recording_made_before_this_ticket_carries_none_either(self):
        """A missing `cached_tags` is absent, not a bug."""
        book = self.source(Replay("sparse-isbn-reply.json", folder=HAND_MADE)).by_isbn(
            CRAGSIDE
        )

        self.assertEqual(book.genres, ())

    def test_an_isbn_hardcover_has_no_edition_of_is_an_empty_reply(self):
        """A different empty from "no genres": there is no book at all."""
        self.assertIsNone(
            self.source("by-isbn-9781473225374-genres.json").by_isbn(self.NO_EDITION)
        )

    def test_both_queries_ask_for_the_genres(self):
        """The two shipped queries are the whole ask; nothing else fetches a book."""
        self.assertIn("cached_tags", hardcover.QUERY)
        self.assertIn("cached_tags", hardcover.TITLE_QUERY)


# Every field Colophon writes that Hardcover holds, and the name the schema
# gives it on the wire. `Candidate` calls the release date `date` and the ISBN
# `isbn`; the edition calls them `release_date` and `isbn_10`/`isbn_13`, and
# either ISBN answers for the one payload field, which is why one entry here
# names two columns. A field Colophon writes appears in the query that fetches
# it or the write silently has nothing to write: that is CBO-73, where the
# title query traded the ISBNs away for the publisher and the date.
ASKED_FOR = {
    "title": ("title",),
    "authors": ("author",),
    "series": ("book_series",),
    "series_number": ("position",),
    "description": ("description",),
    "publisher": ("publisher",),
    "date": ("release_date",),
    "isbn": ("isbn_10", "isbn_13"),
    "language": ("language",),
}


def selection_set(query):
    """The fields a query returns, with every argument taken out of it.

    Arguments go first because the `where` clause spells out field names too,
    and `QUERY` filters on `isbn_13` while selecting it. Checking the whole
    string cannot tell a field that is fetched from one that is only filtered
    on, and a query doing the latter returns no ISBN while reading as correct.
    """
    fields, depth, arguments = None, 0, 0
    for character in query:
        if character == "(":
            arguments += 1
        elif character == ")":
            arguments -= 1
        elif arguments:
            continue
        elif character == "{":
            depth += 1
            if fields is None:
                fields = ""
        elif character == "}":
            depth -= 1
            if depth == 0:
                return fields
        elif fields is not None:
            fields += character
    return fields or ""


def asks_for(query):
    """Which of the fields Colophon writes this query fetches. See `ASKED_FOR`."""
    fields = selection_set(query)
    return {
        name for name, wanted in ASKED_FOR.items() if any(w in fields for w in wanted)
    }


class QueryFieldTests(unittest.TestCase):
    """What each shipped query asks Hardcover for, read off the wire.

    The committed fixtures predate CBO-38 and still carry the ISBNs, so a reply
    parsed out of one says nothing about what the query asks for today. These
    read the request instead: a field missing from it is a field lost, whatever
    an older recording happens to contain.
    """

    def sent(self, language):
        """The query `by_title` puts on the wire for a language of this length."""
        replay = Replay()
        Hardcover(TOKEN, transport=replay).by_title(["A Title"], language)
        return replay.sent["body"]["query"]

    def test_every_written_field_is_asked_for_on_every_path(self):
        """The general form of CBO-73: nothing Colophon writes is left unfetched."""
        paths = {
            "the ISBN path": self.isbn_path_query(),
            "a two-letter language": self.sent("en"),
            "a three-letter language": self.sent("eng"),
            "no language at all": self.sent(None),
        }

        for path, query in paths.items():
            with self.subTest(path=path):
                self.assertEqual(
                    asks_for(query),
                    set(ASKED_FOR),
                    f"{path} does not fetch everything Colophon writes",
                )

    def test_the_title_variants_ask_for_the_same_fields(self):
        """Three copies of one query is how CBO-73 happened: they must not drift."""
        by_length = [self.sent("en"), self.sent("eng"), self.sent(None)]

        self.assertEqual([asks_for(query) for query in by_length], [set(ASKED_FOR)] * 3)

    def test_a_field_only_filtered_on_is_not_fetched(self):
        """The shape the checks above have to fail on, since CBO-73 was that shape.

        An ISBN asked about but not asked for is a query that returns no ISBN,
        and `_eq` in the argument spells the field name just as the selection
        does. Reading the whole string passes this, which is why it is read
        without the arguments.
        """
        filtered = hardcover.QUERY.replace("    isbn_13\n    isbn_10\n", "")

        self.assertIn("isbn_13", filtered)
        self.assertNotIn("isbn_13", selection_set(filtered))
        self.assertEqual(set(ASKED_FOR) - asks_for(filtered), {"isbn"})

    def isbn_path_query(self):
        """The query `by_isbn` puts on the wire."""
        replay = Replay()
        Hardcover(TOKEN, transport=replay).by_isbn(CRAGSIDE)
        return replay.sent["body"]["query"]


class GenreSplitTests(unittest.TestCase):
    """The splitter itself, on the shape no recording was kept of."""

    def test_a_semicolon_list_is_several_genres(self):
        self.assertEqual(
            genre_parts("Classics; Fantasy; Horror"),
            ("Classics", "Fantasy", "Horror"),
        )

    def test_a_colon_path_is_several_genres(self):
        self.assertEqual(genre_parts("Fantasy:Humour"), ("Fantasy", "Humour"))

    def test_an_ordinary_genre_is_left_alone(self):
        """`Science Fiction & Fantasy` is one of the spellings the model judges."""
        self.assertEqual(
            genre_parts("Science Fiction & Fantasy"), ("Science Fiction & Fantasy",)
        )

    def test_empties_are_dropped(self):
        self.assertEqual(genre_parts("Crime; ;"), ("Crime",))


if __name__ == "__main__":
    unittest.main()
