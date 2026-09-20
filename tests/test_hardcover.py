"""Tests for the Hardcover source: what it asks for, and what it makes of the reply.

The replies are real recordings from Hardcover's API, replayed here, so the
suite needs no key and never touches the network. See
`fixtures/hardcover/README.md` for what each one is.
"""

import json
import unittest
from pathlib import Path

from colophon.hardcover import Hardcover
from colophon.sources import SourceError
from tests.tempdir import TemporaryDirectory

RECORDED = Path(__file__).parent / "fixtures" / "hardcover"
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
    """Stands in for the network: hands back a recorded reply, remembers the request."""

    def __init__(self, name="by-isbn-found.json", status=200):
        self.body = (RECORDED / name).read_bytes()
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
        """The older recordings have no ids; a missing one is absent, not a bug."""
        book = self.source(Replay("by-isbn-found.json")).by_isbn(CRAGSIDE)

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
        source = self.source(Replay("hand-made-work-without-title.json"))

        book = source.by_isbn(A_HAND_MADE_BOOK)

        self.assertEqual(book.title, "The Edition Title")
        self.assertEqual(book.language, "fr")

    def test_it_takes_authors_and_leaves_the_translator_behind(self):
        """A reply wider than the question is filtered again, not trusted."""
        source = self.source(Replay("hand-made-wider-than-the-question.json"))

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
        """Mistborn is in three series, and Hardcover lists the featured one last."""
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

    def test_it_reads_berwick_and_belsay_too(self):
        """Belsay's file carries no series number; Hardcover has #23."""
        berwick = self.source(Replay("by-title-berwick.json")).by_title([BERWICK_TITLE], "en")
        belsay = self.source(Replay("by-title-belsay.json")).by_title([BELSAY_TITLE], "en")

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
                                {"contribution": "Author", "author": {"name": "L.J. Ross"}}
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
                                {"contribution": "Author", "author": {"name": "L.J. Ross"}}
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
                    {"title": "Cragside", "language": None, "book": {"title": "Cragside"}},
                    {"title": "Cragside", "language": None, "book": {"title": "Cragside"}},
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
        source = Hardcover(TOKEN, transport=answering(401, b'{"error":"invalid_token"}'))

        with self.assertRaises(SourceError) as caught:
            source.by_isbn(CRAGSIDE)

        self.assertIn("token", str(caught.exception))

    def test_a_token_without_the_right_scope_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(403, b'{"error":"forbidden"}'))

        with self.assertRaises(SourceError):
            source.by_isbn(CRAGSIDE)

    def test_rate_limiting_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(429, b'{"error":"Too Many Requests"}'))

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

                self.assertEqual(replay.sent["headers"]["Authorization"], f"Bearer {TOKEN}")

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
        """Hardcover has neither for Normal People, and neither is invented."""
        book = self.source("by-isbn-no-series.json").by_isbn(NORMAL_PEOPLE)

        self.assertIsNone(book.publisher)
        self.assertIsNone(book.cover)

    def test_the_title_path_carries_them_too(self):
        candidates = self.source("by-title-cragside-other-fields.json").by_title(
            [CRAGSIDE_TITLE], "en"
        )

        self.assertTrue(candidates[0].description.startswith("FROM THE #1 INTERNATIONAL"))
        self.assertEqual(candidates[0].publisher, "Independently Published")
        self.assertTrue(candidates[0].cover.startswith("https://assets.hardcover.app/"))


if __name__ == "__main__":
    unittest.main()
