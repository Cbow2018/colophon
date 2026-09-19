"""Tests for the Hardcover source: what it asks for, and what it makes of the reply."""

import json
import unittest
from pathlib import Path

from colophon.hardcover import Hardcover, SourceError
from tests.tempdir import TemporaryDirectory

RECORDED = Path(__file__).parent / "fixtures" / "hardcover"
TOKEN = "hardcover-token-that-must-never-be-logged"


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
        book = self.source().by_isbn("9781786813891")

        self.assertEqual(book.source, "hardcover")
        self.assertEqual(book.title, "Cragside")
        self.assertEqual(book.authors, ("LJ Ross",))
        self.assertEqual(book.series, "DCI Ryan")
        self.assertEqual(book.series_number, "6")
        self.assertEqual(book.language, "en")
        self.assertEqual(book.isbn, "9781786813891")

    def test_an_isbn_no_edition_carries_is_not_a_match(self):
        source = self.source(Replay("by-isbn-not-found.json"))

        self.assertIsNone(source.by_isbn("9780000000001"))

    def test_it_asks_about_editions_because_books_carry_no_isbn(self):
        replay = Replay()

        self.source(replay).by_isbn("9781786813891")

        query = replay.sent["body"]["query"]
        self.assertIn("editions", query)
        self.assertIn("isbn_13", query)
        self.assertIn("isbn_10", query)
        self.assertIn("book_series", query)
        self.assertIn("language", query)

    def test_the_isbn_is_sent_as_a_variable_and_not_spliced_into_the_query(self):
        replay = Replay()

        self.source(replay).by_isbn("9781786813891")

        self.assertEqual(replay.sent["body"]["variables"], {"isbn": "9781786813891"})
        self.assertNotIn("9781786813891", replay.sent["body"]["query"])

    def test_it_takes_the_work_title_rather_than_the_edition_blurb(self):
        book = self.source().by_isbn("9781786813891")

        self.assertEqual(book.title, "Cragside")

    def test_it_falls_back_to_the_edition_title_when_the_work_has_none(self):
        source = self.source(Replay("by-isbn-edition-title-only.json"))

        book = source.by_isbn("9780000000003")

        self.assertEqual(book.title, "The Edition Title")
        self.assertEqual(book.language, "fr")

    def test_it_takes_authors_and_leaves_the_translator_behind(self):
        book = self.source().by_isbn("9781786813891")

        self.assertEqual(book.authors, ("LJ Ross",))

    def test_a_standalone_book_comes_back_with_no_series_or_language(self):
        source = self.source(Replay("by-isbn-no-series.json"))

        book = source.by_isbn("9780000000002")

        self.assertEqual(book.title, "A Standalone Novel")
        self.assertIsNone(book.series)
        self.assertIsNone(book.series_number)
        self.assertIsNone(book.language)

    def test_it_names_itself_to_the_source(self):
        replay = Replay()

        self.source(replay).by_isbn("9781786813891")

        self.assertEqual(replay.sent["url"], "https://api.hardcover.app/v1/graphql")
        self.assertIn("Colophon", replay.sent["headers"]["User-Agent"])
        self.assertEqual(replay.sent["headers"]["Content-Type"], "application/json")


class ErrorTests(unittest.TestCase):
    def test_a_rejected_token_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(401, b'{"error":"invalid_token"}'))

        with self.assertRaises(SourceError) as caught:
            source.by_isbn("9781786813891")

        self.assertIn("token", str(caught.exception))

    def test_a_token_without_the_right_scope_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(403, b'{"error":"forbidden"}'))

        with self.assertRaises(SourceError):
            source.by_isbn("9781786813891")

    def test_rate_limiting_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(429, b'{"error":"Too Many Requests"}'))

        with self.assertRaises(SourceError):
            source.by_isbn("9781786813891")

    def test_a_server_error_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(500, b"<html>oops</html>"))

        with self.assertRaises(SourceError):
            source.by_isbn("9781786813891")

    def test_a_reply_that_is_not_json_is_a_source_problem(self):
        source = Hardcover(TOKEN, transport=answering(200, b"not json at all"))

        with self.assertRaises(SourceError):
            source.by_isbn("9781786813891")

    def test_graphql_errors_in_the_reply_are_a_source_problem(self):
        source = Hardcover(
            TOKEN, transport=answering(200, b'{"errors":[{"message":"no such field"}]}')
        )

        with self.assertRaises(SourceError):
            source.by_isbn("9781786813891")

    def test_a_reply_that_does_not_answer_the_question_is_a_source_problem(self):
        """Better to say we could not ask than to report a book as not found."""
        source = Hardcover(TOKEN, transport=answering(200, b'{"data":{}}'))

        with self.assertRaises(SourceError):
            source.by_isbn("9781786813891")

    def test_a_network_failure_is_a_source_problem(self):
        def refuse(url, headers, body):
            raise OSError("connection refused")

        with self.assertRaises(SourceError):
            Hardcover(TOKEN, transport=refuse).by_isbn("9781786813891")

    def test_the_token_never_reaches_the_error_message(self):
        """Even when the failure itself quotes the headers it was given."""
        def echoing(url, headers, body):
            raise OSError(f"could not send {headers}")

        source = Hardcover(TOKEN, transport=echoing)

        with self.assertRaises(SourceError) as caught:
            source.by_isbn("9781786813891")

        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertIn("[token]", str(caught.exception))


class SecretFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_the_token_comes_from_the_secret_file(self):
        secret = self.folder / "hardcover_token"
        secret.write_text(TOKEN + "\n", encoding="utf-8")
        replay = Replay()

        source = Hardcover.from_secret_file(secret, transport=replay)
        source.by_isbn("9781786813891")

        self.assertEqual(replay.sent["headers"]["Authorization"], f"Bearer {TOKEN}")

    def test_no_secret_file_means_there_is_no_source(self):
        self.assertIsNone(Hardcover.from_secret_file(self.folder / "hardcover_token"))

    def test_an_empty_secret_file_means_there_is_no_source(self):
        secret = self.folder / "hardcover_token"
        secret.write_text("   \n", encoding="utf-8")

        self.assertIsNone(Hardcover.from_secret_file(secret))

    def test_a_secret_file_that_cannot_be_read_is_a_source_problem(self):
        unreadable = self.folder / "hardcover_token"
        unreadable.mkdir()

        with self.assertRaises(SourceError):
            Hardcover.from_secret_file(unreadable)


if __name__ == "__main__":
    unittest.main()
