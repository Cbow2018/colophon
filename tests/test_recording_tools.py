"""Tests for the recorder in `tools/`: the pacing and the 429 retry, and nothing else.

The recorder is not a module the package imports, and its job is to talk to two
live APIs, so what is worth testing is the part that decides whether to ask again
and how long to wait. Everything else it does is either a request the shipped
client built or a file write. See `docs/recording-fixtures.md`.
"""

import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

RECORDER_PATH = Path(__file__).resolve().parent.parent / "tools" / "record-fixtures.py"


def load_recorder():
    """The recorder module, from its path: its name has a hyphen in it."""
    spec = importlib.util.spec_from_file_location("record_fixtures", RECORDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recorder = load_recorder()

# What Hardcover actually answered when the free tier was asked too fast.
RATE_LIMITED = json.dumps(
    {"error": "API rate limit exceeded for tier 'Free (JWT)'. Try again in 1 seconds."}
).encode("utf-8")


@contextlib.contextmanager
def sleeping():
    """A stand-in for `time.sleep`, and silence for the line the retry prints.

    Both are needed in every `_send` test, and chaining them as one context keeps
    the tests from nesting four `with` blocks deep.
    """
    with (
        mock.patch.object(recorder.time, "sleep") as sleep,
        mock.patch("sys.stdout", new=io.StringIO()),
    ):
        yield sleep


class RetryHintTests(unittest.TestCase):
    """The delay a 429 asks for, read from whichever place it puts it."""

    def test_it_reads_the_seconds_out_of_the_retry_after_header(self):
        self.assertEqual(recorder._retry_after({"Retry-After": "1"}), 1.0)
        self.assertEqual(recorder._retry_after({"Retry-After": "2.5"}), 2.5)

    def test_no_header_is_no_hint_rather_than_no_delay(self):
        self.assertIsNone(recorder._retry_after({}))
        self.assertIsNone(recorder._retry_after(None))

    def test_an_http_date_is_no_hint(self):
        """Guessing wrong means sleeping for the wrong length, so it is not guessed."""
        headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}

        self.assertIsNone(recorder._retry_after(headers))

    def test_it_reads_the_delay_out_of_hardcovers_own_message(self):
        self.assertEqual(recorder._hinted_delay(RATE_LIMITED), 1.0)

    def test_a_message_with_no_delay_falls_back_to_the_default(self):
        self.assertEqual(
            recorder._hinted_delay(json.dumps({"error": "too many requests"})),
            recorder.DEFAULT_RETRY_SECONDS,
        )

    def test_a_body_that_is_not_a_message_falls_back_too(self):
        for body in (b"not json", b"[]", b'{"error": {"nested": true}}', b""):
            with self.subTest(body=body):
                self.assertEqual(
                    recorder._hinted_delay(body), recorder.DEFAULT_RETRY_SECONDS
                )


class SendTests(unittest.TestCase):
    """`_send` asks again after a 429, and stops asking eventually."""

    def test_a_200_is_returned_without_waiting(self):
        with (
            mock.patch.object(recorder, "_once", return_value=(200, b"{}", None)),
            sleeping() as sleep,
        ):
            self.assertEqual(recorder._send("a request"), (200, b"{}"))

        sleep.assert_not_called()

    def test_a_429_is_waited_out_for_the_delay_it_asked_for(self):
        replies = [(429, RATE_LIMITED, None), (200, b'{"ok": true}', None)]

        with (
            mock.patch.object(recorder, "_once", side_effect=replies) as once,
            sleeping() as sleep,
        ):
            self.assertEqual(recorder._send("a request"), (200, b'{"ok": true}'))

        self.assertEqual(once.call_count, 2, "it asked again")
        sleep.assert_called_once_with(1.0)

    def test_the_retry_after_header_wins_over_the_message(self):
        replies = [(429, RATE_LIMITED, 7.0), (200, b"{}", None)]

        with (
            mock.patch.object(recorder, "_once", side_effect=replies),
            sleeping() as sleep,
        ):
            recorder._send("a request")

        sleep.assert_called_once_with(7.0)

    def test_it_gives_up_after_the_retry_budget_and_returns_the_429(self):
        with (
            mock.patch.object(
                recorder, "_once", return_value=(429, RATE_LIMITED, None)
            ) as once,
            sleeping(),
        ):
            status, body = recorder._send("a request")

        self.assertEqual(status, 429)
        self.assertEqual(body, RATE_LIMITED)
        self.assertEqual(once.call_count, recorder.RETRIES_ON_429 + 1)

    def test_a_500_is_a_refusal_and_is_not_retried(self):
        with (
            mock.patch.object(recorder, "_once", return_value=(500, b"oh no", None)),
            sleeping() as sleep,
        ):
            self.assertEqual(recorder._send("a request"), (500, b"oh no"))

        sleep.assert_not_called()


class PaceTests(unittest.TestCase):
    """The pause between Hardcover requests, which is what avoids the 429 at all."""

    def setUp(self):
        recorder._paced["last"] = None
        self.addCleanup(lambda: recorder._paced.update(last=None))

    def test_the_first_request_does_not_wait(self):
        with sleeping() as sleep:
            recorder.pace(1.5)

        sleep.assert_not_called()

    def test_a_second_request_inside_the_pause_waits_the_remainder(self):
        recorder._paced["last"] = 100.0

        with (
            mock.patch.object(recorder.time, "monotonic", return_value=100.5),
            sleeping() as sleep,
        ):
            recorder.pace(1.5)

        sleep.assert_called_once_with(1.5 - 0.5)

    def test_a_request_after_the_pause_does_not_wait(self):
        recorder._paced["last"] = 100.0

        with (
            mock.patch.object(recorder.time, "monotonic", return_value=102.0),
            sleeping() as sleep,
        ):
            recorder.pace(1.5)

        sleep.assert_not_called()

    def test_a_pace_of_zero_turns_the_pacing_off(self):
        recorder._paced["last"] = 100.0

        with sleeping() as sleep:
            recorder.pace(0)

        sleep.assert_not_called()


class CaptureKeyTests(unittest.TestCase):
    """The captures are kept under a key that names the source as well as the file.

    `by-title-cragside.json` is declared under both sources. Keying the captures
    on the fixture name alone let the second source's reply stand in for the
    first: `fixtures/hardcover/` got a Google body and `fixtures/googlebooks/`
    got a Hardcover one, and the run reported success throughout.
    """

    def test_the_corpus_really_does_share_names_across_sources(self):
        """If this stops being true the tests below prove nothing."""
        names = [row["fixture"] for row in recorder.RECORDINGS]
        shared = {name for name in names if names.count(name) > 1}

        self.assertEqual(
            shared,
            {
                "by-isbn-cragside-authors.json",
                "by-title-belsay.json",
                "by-title-berwick.json",
                "by-title-cragside-other-fields.json",
                "by-title-cragside.json",
                "by-title-poe.json",
                "by-title-the-infirmary.json",
            },
        )

    def test_each_capture_is_keyed_by_its_source_and_its_name(self):
        keys = [recorder.label(row) for row in recorder.RECORDINGS]

        self.assertEqual(len(keys), len(set(keys)), "two rows share a capture key")

    def test_one_sources_reply_cannot_stand_in_for_the_others(self):
        rows = [
            {"source": "hardcover", "fixture": "by-title-cragside.json"},
            {"source": "googlebooks", "fixture": "by-title-cragside.json"},
        ]

        replies = {recorder.label(row): row["source"] for row in rows}

        self.assertEqual(len(replies), 2)
        self.assertEqual(replies["hardcover/by-title-cragside.json"], "hardcover")
        self.assertEqual(replies["googlebooks/by-title-cragside.json"], "googlebooks")

    def test_a_body_of_the_wrong_shape_is_refused_before_anything_is_written(self):
        """A cross-source mix-up stops the run instead of corrupting the corpus.

        The check lives in `collect`, which is where every reply passes through
        before any file is opened, so a wrong-shape body never reaches `write`.
        """
        rows = [{"source": "hardcover", "fixture": "by-title-cragside.json"}]
        google_body = {"totalItems": 2, "items": []}

        with (
            mock.patch.object(recorder, "capture", return_value=(google_body, None)),
            mock.patch("sys.stdout", new=io.StringIO()),
        ):
            replies, problem = recorder.collect(rows, "a-token", "a-key", 0)

        self.assertIsNone(replies)
        self.assertIn("googlebooks", problem)
        self.assertIn("hardcover", problem)

    def test_each_sources_reply_lands_in_its_own_directory(self):
        """The whole run, with the two sources answering differently on purpose."""
        rows = [
            {"source": "hardcover", "fixture": "by-title-cragside.json"},
            {"source": "googlebooks", "fixture": "by-title-cragside.json"},
            {"source": "hardcover", "fixture": "by-title-belsay.json"},
            {"source": "googlebooks", "fixture": "by-title-belsay.json"},
        ]
        bodies = {
            "hardcover": {"data": {"editions": [{"title": "from hardcover"}]}},
            "googlebooks": {"totalItems": 1, "items": [{"id": "from google"}]},
        }
        written = {}

        def capture(row, *_args, **_kwargs):
            return bodies[row["source"]], None

        with (
            mock.patch.object(recorder, "capture", side_effect=capture),
            mock.patch("sys.stdout", new=io.StringIO()),
            mock.patch.object(
                recorder,
                "fixture_path",
                side_effect=lambda name, source: Path(f"{source}/{name}"),
            ),
            mock.patch.object(
                Path,
                "write_text",
                lambda self, text, encoding=None: written.update({str(self): text}),
            ),
            mock.patch.object(Path, "relative_to", lambda self, other: self),
        ):
            replies, problem = recorder.collect(rows, "a-token", "a-key", 0)
            recorder.write(rows, replies)

        self.assertIsNone(problem)
        self.assertEqual(
            {path.replace("\\", "/") for path in written},
            {
                "hardcover/by-title-cragside.json",
                "googlebooks/by-title-cragside.json",
                "hardcover/by-title-belsay.json",
                "googlebooks/by-title-belsay.json",
            },
        )
        for path, text in written.items():
            source = path.replace("\\", "/").split("/")[0]
            expected = "from hardcover" if source == "hardcover" else "from google"
            with self.subTest(path=path):
                self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
