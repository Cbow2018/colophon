"""Tests for the LLM fallback chooser: the request, the reply, and the limit.

The replies are real recordings from DeepSeek's OpenAI-compatible API, replayed
here, so the suite needs no key and never touches the network. See
`fixtures/llm/README.md` for what each one is; DeepSeek is the only provider
that was ever called.
"""

import datetime
import json
import unittest
from pathlib import Path

from colophon.backups import Backups
from colophon.config import Config, load_config
from colophon.correction import Corrector, top_candidates
from colophon.epub import read
from colophon.llm import PROVIDERS, Llm, LlmError, LlmLimited
from colophon.matching import Candidate, FileBook
from colophon.sources import SourceError
from tests.samplebooks import HOLY_ISLAND as HOLY_ISLAND_BOOK
from tests.samplebooks import write_epub
from tests.sources import FakeSource
from tests.tempdir import TemporaryDirectory

RECORDED = Path(__file__).parent / "fixtures" / "llm"
KEY = "llm-secret-key-4242"

# The candidates the three contract recordings were made against: the real
# Hardcover records, as the prompt numbers them.
BELSAY_RECORD = Candidate(
    source="hardcover",
    title="Belsay",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="23",
    language="en",
    isbn="9781999761009",
    publisher="Independently Published",
    date="2021-05-01",
)
BERWICK = Candidate(
    source="hardcover",
    title="Berwick",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="24",
    language="en",
)
HOLY_ISLAND = Candidate(
    source="google_books",
    title="Holy Island",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="1",
    language="en",
)
THE_INFIRMARY = Candidate(
    source="hardcover",
    title="The Infirmary",
    authors=("Carly Reagon",),
    language="en",
)
FILE = {"title": "Belsay (The DCI Ryan Mysteries Book 23)", "filename": "Belsay.epub"}


class Replay:
    """Stands in for the network: hands back a recorded reply, remembers the request."""

    def __init__(self, *names, status=200, body=None):
        self.bodies = [(RECORDED / name).read_bytes() for name in names]
        self.status = status
        self.body = body
        self.sent = []

    def __call__(self, url, headers, request):
        self.sent.append({"url": url, "headers": headers, "body": json.loads(request)})
        if self.body is not None:
            return self.status, self.body
        return self.status, self.bodies[min(len(self.sent), len(self.bodies)) - 1]


def today():
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


class LlmTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def client(self, *names, key=KEY, counter=None, limit=200, **kwargs):
        return Llm(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            key=key,
            daily_limit=limit,
            counter=counter or self.tmp / "llm.json",
            transport=Replay(*names, **kwargs),
        )


class ChooseTests(LlmTestCase):
    """The ticket's own two cases, from the recorded replies."""

    def test_belsay_present_among_the_candidates_is_picked(self):
        choice = self.client("belsay-picked.json").choose(
            FILE, [BELSAY_RECORD, BERWICK, HOLY_ISLAND, THE_INFIRMARY]
        )

        self.assertEqual(choice.pick, 1)
        self.assertIs(choice.candidate, BELSAY_RECORD)

    def test_belsay_removed_with_berwick_as_a_lookalike_is_a_null_pick(self):
        choice = self.client("belsay-absent.json").choose(
            FILE, [BERWICK, HOLY_ISLAND, THE_INFIRMARY]
        )

        self.assertIsNone(choice.pick)
        self.assertIsNone(choice.candidate)

    def test_a_null_pick_at_full_confidence_is_still_a_null_pick(self):
        """The model is certain none of them is the book, and it is still no pick."""
        choice = self.client("null-pick-confident.json").choose(
            FILE, [BERWICK, HOLY_ISLAND]
        )

        self.assertIsNone(choice.pick)
        self.assertEqual(choice.confidence, 1.0)


class RequestTests(LlmTestCase):
    def test_the_request_is_the_documented_one(self):
        client = self.client("belsay-picked.json")

        client.choose(FILE, [BELSAY_RECORD])

        sent = client._transport.sent[0]
        self.assertEqual(sent["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(sent["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(sent["body"]["model"], "deepseek-flash")
        self.assertEqual(sent["body"]["response_format"], {"type": "json_object"})
        self.assertIn("max_tokens", sent["body"])
        self.assertNotIn("temperature", sent["body"], "a field some models refuse")
        self.assertNotIn("tools", sent["body"])
        self.assertEqual(
            [message["role"] for message in sent["body"]["messages"]],
            ["system", "user"],
        )

    def test_the_prompt_asks_for_json_by_name(self):
        """DeepSeek refuses `response_format` when the messages never say JSON."""
        client = self.client("belsay-picked.json")

        client.choose(FILE, [BELSAY_RECORD])

        messages = client._transport.sent[0]["body"]["messages"]
        self.assertIn("JSON", messages[0]["content"])

    def test_the_candidate_list_is_numbered_from_one_with_the_fields_asked_for(self):
        client = self.client("belsay-picked.json")

        client.choose(FILE, [BELSAY_RECORD, BERWICK])

        user = client._transport.sent[0]["body"]["messages"][1]["content"]
        self.assertIn("Belsay", user)
        self.assertIn("L.J. Ross", user)
        self.assertIn("DCI Ryan Mysteries", user)
        self.assertIn("23", user)
        self.assertIn("2021", user, "the year is derived from the date")
        self.assertIn("9781999761009", user)
        self.assertIn("en", user)
        self.assertIn("1.", user)
        self.assertIn("2.", user)
        self.assertNotIn("hardcover", user, "a candidate's source is not sent")

    def test_the_file_side_of_the_prompt_keeps_the_raw_title(self):
        client = self.client("belsay-picked.json")

        client.choose(FILE, [BELSAY_RECORD])

        user = client._transport.sent[0]["body"]["messages"][1]["content"]
        self.assertIn("Belsay (The DCI Ryan Mysteries Book 23)", user)
        self.assertIn("Belsay.epub", user)

    def test_a_year_is_only_sent_when_the_date_really_starts_with_one(self):
        odd = Candidate(title="Belsay", authors=("L.J. Ross",), date="2021-05")
        client = self.client("belsay-picked.json")

        client.choose(FILE, [odd])

        user = client._transport.sent[0]["body"]["messages"][1]["content"]
        self.assertNotIn("2021-05", user)
        self.assertIn("2021", user)


class ProviderTests(LlmTestCase):
    def test_every_provider_the_ticket_names_has_a_preset(self):
        self.assertEqual(
            set(PROVIDERS),
            {
                "deepseek",
                "anthropic",
                "gemini",
                "openai",
                "openrouter",
                "groq",
                "ollama",
            },
        )

    def test_deepseek_suggests_the_model_name_the_endpoint_really_serves(self):
        self.assertEqual(PROVIDERS["deepseek"].model, "deepseek-flash")
        self.assertEqual(PROVIDERS["deepseek"].base_url, "https://api.deepseek.com")

    def test_a_trailing_slash_makes_no_difference_to_the_url(self):
        """Strip then add: `urljoin` would replace Gemini's last segment."""
        gemini = "https://generativelanguage.googleapis.com/v1beta/openai"
        self.assertFalse(gemini.endswith("/"), "the case the join has to survive")
        self.assertEqual(PROVIDERS["gemini"].base_url.rstrip("/"), gemini)

        for base in (gemini, gemini + "/"):
            client = Llm(
                provider="gemini",
                model=PROVIDERS["gemini"].model,
                base_url=base,
                key=KEY,
                daily_limit=0,
                counter=self.tmp / "llm.json",
                transport=Replay("belsay-picked.json"),
            )
            client.choose(FILE, [BELSAY_RECORD])
            self.assertEqual(
                client._transport.sent[0]["url"],
                f"{gemini}/chat/completions",
            )

    def test_ollama_needs_no_key(self):
        client = Llm(
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434/v1/",
            key=None,
            daily_limit=0,
            counter=self.tmp / "llm.json",
            transport=Replay("belsay-picked.json"),
        )

        client.choose(FILE, [BELSAY_RECORD])

        self.assertNotIn("Authorization", client._transport.sent[0]["headers"])

    def test_a_key_is_never_sent_to_a_preset_that_says_it_ignores_one(self):
        """Ollama ignores the header; sending it would only leak the secret."""
        client = Llm(
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434/v1/",
            key=KEY,
            daily_limit=0,
            counter=self.tmp / "llm.json",
            transport=Replay("belsay-picked.json"),
        )

        client.choose(FILE, [BELSAY_RECORD])

        self.assertNotIn(KEY, json.dumps(client._transport.sent[0]["headers"]))

    def test_a_provider_that_needs_a_key_says_so(self):
        self.assertTrue(PROVIDERS["openai"].needs_key)
        self.assertFalse(PROVIDERS["ollama"].needs_key)

    def test_anthropic_is_present_and_says_its_json_mode_is_untested(self):
        self.assertFalse(PROVIDERS["anthropic"].json_mode)
        self.assertEqual(
            PROVIDERS["anthropic"].base_url, "https://api.anthropic.com/v1/"
        )


class FromConfigTests(LlmTestCase):
    def config(self, **values):
        return Config(**values)

    def test_no_key_file_means_no_llm_at_all(self):
        llm = Llm.from_config(self.config(llm_key_file=self.tmp / "missing"))

        self.assertIsNone(llm)

    def test_a_key_file_means_an_llm(self):
        secret = self.tmp / "llm_key"
        secret.write_text(KEY + "\n", encoding="utf-8")

        llm = Llm.from_config(
            self.config(llm_key_file=secret, llm_counter_file=self.tmp / "llm.json")
        )

        self.assertEqual(llm.provider, "deepseek")
        self.assertEqual(llm.model, "deepseek-flash")
        self.assertEqual(llm.base_url, "https://api.deepseek.com")

    def test_ollama_works_with_no_key_file(self):
        llm = Llm.from_config(
            self.config(
                llm_provider="ollama",
                llm_key_file=self.tmp / "missing",
                llm_counter_file=self.tmp / "llm.json",
            )
        )

        self.assertIsNotNone(llm)
        self.assertEqual(llm.base_url, PROVIDERS["ollama"].base_url.rstrip("/"))

    def test_a_base_url_and_model_set_in_config_override_the_preset(self):
        secret = self.tmp / "llm_key"
        secret.write_text(KEY, encoding="utf-8")

        llm = Llm.from_config(
            self.config(
                llm_key_file=secret,
                llm_base_url="https://example.invalid/v1",
                llm_model="some-other-model",
                llm_counter_file=self.tmp / "llm.json",
            )
        )

        self.assertEqual(llm.base_url, "https://example.invalid/v1")
        self.assertEqual(llm.model, "some-other-model")

    def test_an_unknown_provider_is_a_plain_error_not_a_traceback(self):
        with self.assertRaises(LlmError) as caught:
            Llm.from_config(
                self.config(llm_provider="nope", llm_key_file=self.tmp / "missing")
            )

        self.assertIn("nope", str(caught.exception))


class NobodyToAskTests(LlmTestCase):
    def test_an_empty_candidate_list_is_never_asked_about(self):
        """The answer is always null, and the call would only spend the limit."""
        client = self.client("belsay-absent.json")

        with self.assertRaises(LlmError):
            client.choose(FILE, [])

        self.assertEqual(client._transport.sent, [])


class LimitTests(LlmTestCase):
    def test_the_limit_counts_every_call(self):
        client = self.client("belsay-picked.json", limit=1)
        client.choose(FILE, [BELSAY_RECORD])

        with self.assertRaises(LlmLimited):
            client.choose(FILE, [BELSAY_RECORD])

        self.assertEqual(len(client._transport.sent), 1)

    def test_zero_means_no_limit(self):
        client = self.client("belsay-picked.json", limit=0)
        for _ in range(3):
            client.choose(FILE, [BELSAY_RECORD])

        self.assertEqual(len(client._transport.sent), 3)

    def test_a_failed_call_still_spends_the_limit(self):
        """A call that fails still costs money and still spends the rate limit."""
        client = self.client(limit=1, status=500, body=b"nope")

        with self.assertRaises(LlmError):
            client.choose(FILE, [BELSAY_RECORD])
        with self.assertRaises(LlmLimited):
            client.choose(FILE, [BELSAY_RECORD])

    def test_the_count_survives_a_restart(self):
        first = self.client("belsay-picked.json", limit=2)
        first.choose(FILE, [BELSAY_RECORD])

        second = self.client("belsay-picked.json", limit=2)
        second.choose(FILE, [BELSAY_RECORD])
        with self.assertRaises(LlmLimited):
            second.choose(FILE, [BELSAY_RECORD])

    def test_yesterdays_count_does_not_count_against_today(self):
        counter = self.tmp / "llm.json"
        counter.write_text(
            json.dumps({"date": "2020-01-01", "calls": 200}), encoding="utf-8"
        )

        client = self.client("belsay-picked.json", limit=2)

        client.choose(FILE, [BELSAY_RECORD])

        self.assertEqual(
            json.loads(counter.read_text(encoding="utf-8"))["date"], today()
        )
        self.assertEqual(json.loads(counter.read_text(encoding="utf-8"))["calls"], 1)

    def test_a_counter_file_that_cannot_be_read_does_not_stop_the_call(self):
        counter = self.tmp / "llm.json"
        counter.write_text("not json at all", encoding="utf-8")

        choice = self.client("belsay-picked.json", counter=counter, limit=0).choose(
            FILE, [BELSAY_RECORD]
        )

        self.assertEqual(choice.pick, 1)

    def test_the_counter_is_written_beside_itself_so_the_swap_is_atomic(self):
        """`os.replace` is only atomic within one filesystem."""
        counter = self.tmp / "nested" / "llm.json"

        client = self.client("belsay-picked.json", counter=counter)
        client.choose(FILE, [BELSAY_RECORD])

        self.assertTrue(counter.exists())
        self.assertEqual([path.name for path in counter.parent.iterdir()], ["llm.json"])


class FailureTests(LlmTestCase):
    def test_a_reply_that_is_not_json_is_null_and_not_an_exception(self):
        client = self.client("prose-not-json.json")

        self.assertIsNone(client.choose(FILE, [BELSAY_RECORD]))

    def test_a_body_that_is_not_json_at_all_is_null(self):
        client = self.client(status=401, body=b"Authentication Fails (governor)")

        with self.assertRaises(LlmError):
            client.choose(FILE, [BELSAY_RECORD])

    def test_a_wrong_key_is_never_echoed_into_the_error(self):
        """DeepSeek's 401 body quotes part of the key back."""
        body = json.dumps(
            {"error": {"message": f"Your api key: ****{KEY[-4:]} is invalid"}}
        )

        with self.assertRaises(LlmError) as caught:
            self.client(status=401, body=body.encode("utf-8")).choose(
                FILE, [BELSAY_RECORD]
            )

        self.assertNotIn(KEY, str(caught.exception))

    def test_a_rejected_key_is_named_as_one(self):
        with self.assertRaises(LlmError) as caught:
            self.client(status=401, body=b"nope").choose(FILE, [BELSAY_RECORD])

        self.assertIn("401", str(caught.exception))

    def test_a_configuration_error_is_logged_as_one(self):
        """A 400 repeats every day, so it must not read like an outage."""
        body = json.dumps({"error": {"message": "no such model"}}).encode("utf-8")

        with (
            self.assertLogs("colophon", level="WARNING") as captured,
            self.assertRaises(LlmError),
        ):
            self.client(status=400, body=body).choose(FILE, [BELSAY_RECORD])

        self.assertIn("configuration", " ".join(captured.output))
        self.assertIn("400", " ".join(captured.output))


class ParsingTests(LlmTestCase):
    def record(self, content, finish="stop"):
        """A reply body carrying this content, shaped the way the API shapes one."""
        return json.dumps(
            {
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": finish,
                    }
                ],
            }
        ).encode("utf-8")

    def choose(self, content, candidates=None, finish="stop"):
        client = self.client(status=200, body=self.record(content, finish))
        return client.choose(FILE, candidates or [BELSAY_RECORD, BERWICK])

    def test_a_pick_that_is_a_boolean_is_not_candidate_one(self):
        """`True` passes `isinstance(x, int)` in Python."""
        self.assertIsNone(self.choose('{"pick": true, "confidence": 0.99}'))

    def test_a_pick_that_is_a_whole_float_is_not_an_integer(self):
        self.assertIsNone(self.choose('{"pick": 1.0, "confidence": 0.99}'))

    def test_a_pick_that_is_a_string_is_not_an_integer(self):
        self.assertIsNone(self.choose('{"pick": "1", "confidence": 0.99}'))

    def test_a_pick_past_the_end_of_the_list_is_a_null(self):
        self.assertIsNone(
            self.choose('{"pick": 3, "confidence": 0.99}', [BELSAY_RECORD, BERWICK])
        )

    def test_a_pick_before_the_start_of_the_list_is_a_null(self):
        self.assertIsNone(self.choose('{"pick": 0, "confidence": 0.99}'))

    def test_a_pick_past_the_end_is_worth_a_warning(self):
        """On its own it is indistinguishable from a bug in our own numbering."""
        with self.assertLogs("colophon", level="WARNING"):
            self.choose('{"pick": 3, "confidence": 0.99}', [BELSAY_RECORD, BERWICK])

    def test_a_confidence_above_one_is_a_null(self):
        self.assertIsNone(self.choose('{"pick": 1, "confidence": 1.5}'))

    def test_a_confidence_below_zero_is_a_null(self):
        self.assertIsNone(self.choose('{"pick": 1, "confidence": -0.1}'))

    def test_a_confidence_that_is_not_a_number_is_a_null(self):
        self.assertIsNone(self.choose('{"pick": 1, "confidence": "high"}'))

    def test_a_truncated_reply_is_a_null_even_when_its_content_parses(self):
        self.assertIsNone(
            self.choose('{"pick": 1, "confidence": 0.9}', finish="length")
        )

    def test_a_reply_carrying_no_choices_is_a_null(self):
        client = self.client(
            status=200, body=json.dumps({"choices": []}).encode("utf-8")
        )

        self.assertIsNone(client.choose(FILE, [BELSAY_RECORD]))

    def test_a_message_with_no_content_is_a_null(self):
        body = json.dumps({"choices": [{"message": {"role": "assistant"}}]}).encode(
            "utf-8"
        )

        self.assertIsNone(
            self.client(status=200, body=body).choose(FILE, [BELSAY_RECORD])
        )

    def test_a_reply_that_is_a_json_array_rather_than_an_object_is_a_null(self):
        self.assertIsNone(self.choose("[1, 2]"))

    def test_a_confidence_that_is_absent_is_read_as_zero(self):
        choice = self.choose('{"pick": 1}')
        self.assertEqual(choice.pick, 1)
        self.assertEqual(choice.confidence, 0.0)


class RedactionTests(LlmTestCase):
    def test_a_key_the_provider_quotes_back_never_reaches_the_error(self):
        body = json.dumps(
            {"error": {"message": f"Your api key: ****{KEY[-4:]} is invalid"}}
        )

        with self.assertRaises(LlmError) as caught:
            self.client(status=401, body=body.encode("utf-8")).choose(
                FILE, [BELSAY_RECORD]
            )

        self.assertNotIn(KEY[-4:], str(caught.exception))

    def test_a_key_the_provider_quotes_back_never_reaches_the_log(self):
        body = json.dumps(
            {"error": {"message": f"Your api key: ****{KEY[-4:]} is invalid"}}
        )

        with (
            self.assertLogs("colophon", level="WARNING") as captured,
            self.assertRaises(LlmError),
        ):
            self.client(status=400, body=body.encode("utf-8")).choose(
                FILE, [BELSAY_RECORD]
            )

        self.assertNotIn(KEY[-4:], " ".join(captured.output))


class ChooserTests(unittest.TestCase):
    """The chooser where it is used: a book the rules could not match.

    The client is the real one and the reply is a real recording, so this covers
    the request, the parsing and the decision together. The file is *Holy Island*
    and the candidates are other books of the series - the real records the
    recordings were made from - so the rules agree on the author and nothing
    else and score 0.6, well under the 0.85 they apply. That is exactly the book
    this ticket exists for.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.backups = Backups(self.folder / "backups")
        self.calls = 0
        self.addCleanup(self._tmp.cleanup)

    def book(self, metadata=HOLY_ISLAND_BOOK, name="Holy Island.epub"):
        return write_epub(self.folder / name, metadata, version="2.0")

    def llm(self, *names, limit=200, **kwargs):
        # One counter file per client, or a limit one test spends would be a
        # limit the next one starts with.
        self.calls += 1
        return Llm(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            key=KEY,
            daily_limit=limit,
            counter=self.folder / f"llm-{self.calls}.json",
            transport=Replay(*names, **kwargs),
        )

    def corrector(self, llm, candidates=(BELSAY_RECORD, BERWICK, THE_INFIRMARY)):
        """The candidates the recordings were made against, and no others.

        *Holy Island* is deliberately not among them: the file is that book, and
        its record would score 1.0 on title and author, so the rules would have
        answered and the LLM would never be reached.
        """
        source = FakeSource(found=None, candidates=list(candidates))
        return Corrector(
            sources=[source],
            backups=self.backups,
            llm=llm,
            fetch=self.offline_cover,
        )

    def offline_cover(self, url):
        raise SourceError(f"a test tried to fetch {url} from the network")

    def test_the_rules_alone_do_not_match_this_book(self):
        """The premise the fallback is built on, checked rather than assumed."""
        path = self.book()

        outcome = self.corrector(None).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)

    def test_a_remembered_reply_picks_the_candidate_and_writes_only_its_values(self):
        path = self.book()
        llm = self.llm("belsay-picked.json")

        outcome = self.corrector(llm).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.source, "hardcover")
        self.assertEqual(read(path).title, "Belsay")
        self.assertEqual(read(path).isbn, BELSAY_RECORD.isbn)

    def test_the_outcome_says_the_llm_chose_and_at_what_confidence(self):
        """The number is the model's own, on its own scale, and the line says so."""
        llm = self.llm("belsay-picked.json")

        outcome = self.corrector(llm).correct(self.book())

        self.assertIn("llm picked", outcome.fragment())
        self.assertIn("1.00", outcome.fragment())
        self.assertIn("its own confidence", outcome.fragment())
        self.assertIn("Belsay", outcome.fragment())

    def test_a_null_pick_goes_to_the_unverified_path(self):
        """The model answered; there is nothing to wait for."""
        path = self.book()
        llm = self.llm("belsay-absent.json")

        outcome = self.corrector(llm).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertFalse(outcome.waiting)
        self.assertIn("llm said none", outcome.fragment())

    def test_a_null_pick_at_full_confidence_is_never_written_from(self):
        llm = self.llm("null-pick-confident.json")

        outcome = self.corrector(llm).correct(self.book())

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertIn(
            "1.00", outcome.fragment(), "the confidence is recorded as evidence"
        )

    def test_a_pick_below_the_threshold_is_not_applied(self):
        path = self.book()

        outcome = self.corrector(self.llm(body=_reply(1, 0.5))).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)

    def test_a_pick_at_the_threshold_is_applied(self):
        """The LLM's own number is what the threshold is applied to."""
        path = self.book()

        outcome = self.corrector(self.llm(body=_reply(1, 0.85))).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Belsay")

    def test_an_llm_that_cannot_be_reached_leaves_the_book_waiting(self):
        path = self.book()
        before = path.read_bytes()

        outcome = self.corrector(self.llm(status=503, body=b"nope")).correct(path)

        self.assertTrue(outcome.waiting)
        self.assertFalse(outcome.unverified)
        self.assertEqual(
            path.read_bytes(), before, "the file is left exactly as it was"
        )

    def test_a_book_that_is_waiting_names_what_it_is_waiting_for(self):
        outcome = self.corrector(self.llm(status=503, body=b"nope")).correct(
            self.book()
        )

        self.assertIn("left in the ingest folder", outcome.fragment())
        self.assertIn("trying again tomorrow", outcome.fragment())
        self.assertIn("503", outcome.fragment())

    def test_the_daily_limit_leaves_the_book_waiting_too(self):
        llm = self.llm("belsay-picked.json", limit=1)
        corrector = self.corrector(llm)
        first, second = self.book(), self.book(name="Berwick.epub")

        corrector.correct(first)
        outcome = corrector.correct(second)

        self.assertTrue(outcome.waiting)
        self.assertIn("daily limit", outcome.fragment())

    def test_a_book_that_is_waiting_is_skipped_on_the_next_pass(self):
        """Or every scan would ask the same question of a limit that is spent."""
        llm = self.llm("belsay-picked.json", limit=1)
        corrector = self.corrector(llm)
        corrector.correct(self.book())
        waiting = self.book(name="Berwick.epub")
        corrector.correct(waiting)

        again = corrector.correct(waiting)

        self.assertFalse(
            again.silent, "the relay still has to be told not to deliver it"
        )
        self.assertTrue(again.waiting)
        self.assertIn("daily limit", again.fragment(), "and it can say why again")

    def test_an_unconfigured_llm_sends_the_book_to_the_unverified_path(self):
        """A fresh install with no key must not hold every uncertain book forever."""
        path = self.book()

        outcome = self.corrector(None).correct(path)

        self.assertTrue(outcome.unverified)
        self.assertFalse(outcome.waiting)

    def test_the_llm_is_never_asked_about_a_book_with_no_candidates(self):
        llm = self.llm("belsay-picked.json")

        outcome = self.corrector(llm, candidates=()).correct(self.book())

        self.assertTrue(outcome.unverified)
        self.assertEqual(llm._transport.sent, [])

    def test_the_llm_is_asked_even_when_there_is_only_one_candidate(self):
        """A rejection is a useful answer."""
        llm = self.llm("belsay-absent.json")

        outcome = self.corrector(llm, candidates=(BERWICK,)).correct(self.book())

        self.assertEqual(len(llm._transport.sent), 1)
        self.assertTrue(outcome.unverified)

    def test_a_candidate_the_rules_could_not_use_is_offered_to_the_llm(self):
        """There is no other reason to ask: the rules read the title and author."""
        llm = self.llm("belsay-picked.json")

        outcome = self.corrector(llm, candidates=(BELSAY_RECORD,)).correct(self.book())

        self.assertTrue(outcome.matched)
        self.assertEqual(len(llm._transport.sent), 1)

    def test_a_book_the_rules_already_matched_never_reaches_the_llm(self):
        """The rules answer this one exactly, so there is nothing to ask about."""
        llm = self.llm("belsay-picked.json")
        self.corrector(llm, candidates=(HOLY_ISLAND,)).correct(self.book())

        self.assertEqual(llm._transport.sent, [])


class TheCandidateCapTests(unittest.TestCase):
    """Only the best few candidates per source are put to the model.

    A long tail of lookalikes would bury the right record and cost tokens for
    it, so a source contributes at most `CANDIDATES_PER_SOURCE` - and, this
    being the point, the best of them by the rules' own score rather than
    whichever five the source happened to list first.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.backups = Backups(self.folder / "backups")
        self.calls = 0
        self.addCleanup(self._tmp.cleanup)

    def llm(self, *names):
        self.calls += 1
        return Llm(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            key=KEY,
            daily_limit=0,
            counter=self.folder / f"llm-{self.calls}.json",
            transport=Replay(*names),
        )

    def corrector(self, llm, candidates):
        return Corrector(
            sources=[FakeSource(found=None, candidates=list(candidates))],
            backups=self.backups,
            llm=llm,
            fetch=self.offline_cover,
        )

    def offline_cover(self, url):
        raise SourceError(f"a test tried to fetch {url} from the network")

    def test_the_one_the_rules_like_best_is_kept_even_when_it_is_listed_last(self):
        """The file is Belsay; the source lists five other books first.

        Every one of the six agrees with the file on nothing, so the outcome is
        the same either way and the log line names Belsay as the nearest either
        way. What differs is which candidates the model is shown, and this is the
        seam that decides it: the cap keeps the best by score, not the first five
        the source happened to list.
        """
        file_book = FileBook("Belsay: A DCI Ryan Mystery", ("L. J. Ross",), "en")
        distractors = [
            Candidate(source="hardcover", title=f"Book {number}", authors=("L. J. Ross",))
            for number in range(1, 6)
        ]
        candidates = distractors + [BELSAY_RECORD]

        kept = top_candidates(file_book, candidates)

        self.assertEqual(len(kept), 5)
        self.assertEqual(kept[0], BELSAY_RECORD, "the best candidate goes first")
        self.assertNotIn(distractors[-1], kept, "and the worst of the tail is dropped")

    def test_the_prompt_numbers_the_candidates_in_the_order_it_gives_them(self):
        """Number 1 is the first line, so a pick of 1 is the best candidate."""
        file_book = FileBook("Belsay: A DCI Ryan Mystery", ("L. J. Ross",), "en")
        distractors = [
            Candidate(source="hardcover", title=f"Book {number}", authors=("L.J. Ross",))
            for number in range(1, 6)
        ]

        kept = top_candidates(file_book, distractors + [BELSAY_RECORD])

        self.assertEqual(kept, [BELSAY_RECORD, *distractors[:4]])

    def test_every_candidate_is_kept_when_there_are_no_more_than_the_cap(self):
        file_book = FileBook("Belsay: A DCI Ryan Mystery", ("L. J. Ross",), "en")
        candidates = [BELSAY_RECORD, BERWICK]

        self.assertEqual(top_candidates(file_book, candidates), candidates)


def _reply(pick, confidence):
    content = json.dumps(
        {"pick": pick, "confidence": confidence, "reason": "a recorded reason"}
    )
    return json.dumps(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ]
        }
    ).encode("utf-8")


class ConfiguredLimitTests(unittest.TestCase):
    def test_the_daily_limit_defaults_to_two_hundred(self):
        config = load_config(env={"COLOPHON_CONFIG": "no-such-file.toml"})
        self.assertEqual(config.llm_daily_limit, 200)

    def test_the_environment_can_change_the_daily_limit(self):
        config = load_config(
            env={
                "COLOPHON_CONFIG": "no-such-file.toml",
                "COLOPHON_LLM_DAILY_LIMIT": "5",
            }
        )
        self.assertEqual(config.llm_daily_limit, 5)

    def test_zero_is_a_limit_the_user_can_choose(self):
        config = load_config(
            env={
                "COLOPHON_CONFIG": "no-such-file.toml",
                "COLOPHON_LLM_DAILY_LIMIT": "0",
            }
        )
        self.assertEqual(config.llm_daily_limit, 0)

    def test_a_negative_limit_is_refused(self):
        from colophon.config import ConfigError

        with self.assertRaises(ConfigError):
            load_config(
                env={
                    "COLOPHON_CONFIG": "no-such-file.toml",
                    "COLOPHON_LLM_DAILY_LIMIT": "-1",
                }
            )


if __name__ == "__main__":
    unittest.main()
