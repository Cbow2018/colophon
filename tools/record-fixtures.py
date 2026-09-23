"""Re-record the committed source fixtures against the queries shipped today.

The point of this script is that it cannot encode a query by hand. Every request
it sends is the one the shipped `GoogleBooks` or `Hardcover` client builds for the
book `tests/recordings.py` names, read off the wire, so a query that changes in
`colophon/` changes what this captures in the same commit. That is the same
mechanism the fixture-query guard uses, which is why the two can only agree.

The token and the key come from the environment and are never written anywhere:

    $env:COLOPHON_HARDCOVER_TOKEN = "<the token>"
    $env:COLOPHON_GOOGLE_BOOKS_KEY = "<the key>"

Run without arguments to see the plan, or with a fixture name to write one file:

    python tools/record-fixtures.py --list
    python tools/record-fixtures.py googlebooks/by-title-poe.json

Hardcover's free tier rate-limits by requests per second, so the run pauses
between its requests and waits out a 429 rather than failing the run. Nothing is
written until every requested capture has come back clean, so a run that fails
halfway leaves the committed fixtures as they were. See
`docs/recording-fixtures.md` for the full procedure.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.recordings import (
    RECORDINGS,
    SKIPPED,
    fixture_path,
    sent_request,
)

TOKEN_VARIABLE = "COLOPHON_HARDCOVER_TOKEN"
KEY_VARIABLE = "COLOPHON_GOOGLE_BOOKS_KEY"
USER_AGENT = "Colophon (+https://github.com/Cbow2018/colophon)"
TIMEOUT_SECONDS = 30

# Hardcover's free tier rate-limits by requests per second and answers 429 when
# asked faster, so the run paces itself rather than relying on the retry. 1.5
# seconds between Hardcover requests is what a free-tier token needs to get
# through the 22 in one pass; Google answers all 13 without complaint and is not
# paced. Override with `--pace` if the tier changes.
HARDCOVER_PACE_SECONDS = 1.5

# How many times a 429 is waited out before the run gives up. Each wait is the
# source's own "try again in N seconds", so this bounds the patience, not the
# delay.
RETRIES_ON_429 = 5

# Used when a 429 arrives with nothing to go on. Hardcover's measured hint was
# one second; rounding up costs a second and saves a second failed request.
DEFAULT_RETRY_SECONDS = 2.0


def hardcover_post(request, token):
    """One POST to Hardcover, with whatever status came back."""
    url = "https://api.hardcover.app/v1/graphql"
    body = json.dumps(request).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    return _send(urllib.request.Request(url, data=body, headers=headers, method="POST"))


def google_get(request, key):
    """One GET to Google, with whatever status came back."""
    params = dict(request, key=key)
    url = "https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode(
        params
    )
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    return _send(urllib.request.Request(url, headers=headers, method="GET"))


def _send(request):
    """One request, waiting out a 429 for as long as the source asks.

    A 429 is not a refusal, it is "not yet": the reply carries the delay to wait,
    in a `Retry-After` header or in the body's own message, so the run sleeps for
    exactly that and asks again. Google's 429 is the other kind — a spent daily
    quota that resets tomorrow — and no amount of sleeping helps, but the retry
    budget runs out and the run stops with the reason, which is the right outcome
    for both.
    """
    for attempt in range(RETRIES_ON_429 + 1):
        status, body, retry_after = _once(request)
        if status != 429:
            return status, body
        if attempt == RETRIES_ON_429:
            return status, body
        delay = retry_after if retry_after is not None else _hinted_delay(body)
        print(f"    429: waiting {delay:g}s and asking again")
        time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover - the loop always returns


def _once(request):
    """One attempt, with the retry hint out of the headers if there is one."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(), _retry_after(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), _retry_after(error.headers)


def _retry_after(headers):
    """The `Retry-After` header in seconds, or None when there is not one.

    The header is documented as either a number of seconds or an HTTP date; the
    sources here answer with the number, and a date is treated as no hint rather
    than parsed, because guessing wrong means sleeping for the wrong length.
    """
    if headers is None:
        return None
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return None


def _hinted_delay(body):
    """The delay a 429's own message asks for: "Try again in 1 seconds"."""
    try:
        message = json.loads(body).get("error", "")
    except (ValueError, AttributeError):
        return DEFAULT_RETRY_SECONDS
    if not isinstance(message, str):
        return DEFAULT_RETRY_SECONDS
    found = re.search(r"try again in (\d+(?:\.\d+)?)", message, re.IGNORECASE)
    return float(found.group(1)) if found else DEFAULT_RETRY_SECONDS


def pace(seconds):
    """Wait out the pause since the last Hardcover request, if there is one.

    The wait is measured from the *start* of the previous request rather than its
    end, so a slow reply does not then also pay the full pause.
    """
    if seconds <= 0 or _paced["last"] is None:
        return
    remaining = seconds - (time.monotonic() - _paced["last"])
    if remaining > 0:
        time.sleep(remaining)


# When the last Hardcover request went out. Module state rather than a closure
# because the pacing has to hold across every row in the run.
_paced = {"last": None}


def _mark_asked():
    _paced["last"] = time.monotonic()


def capture(row, token, key, pace_seconds=HARDCOVER_PACE_SECONDS):
    """The reply for one fixture, with anything that is not an answer refused.

    An error reply is never saved as a fixture: a body carrying `errors` (GraphQL)
    or `error` (Google) is a refusal, and a non-2xx is a refusal whatever the body
    says. That is the same rule the earlier recording sessions followed, and it is
    why a fixture on disk is always an answer.
    """
    request = sent_request(row, token=token, key=key)
    if row["source"] == "hardcover":
        pace(pace_seconds)
        _mark_asked()
        status, body = hardcover_post(request, token)
    else:
        status, body = google_get(request, key)

    try:
        payload = json.loads(body)
    except ValueError as error:
        return None, f"HTTP {status}, not JSON: {error}"

    if not 200 <= status < 300:
        return None, f"HTTP {status}: {json.dumps(payload)[:200]}"
    if payload.get("error") or payload.get("errors"):
        return None, f"HTTP {status}, a refusal: {json.dumps(payload)[:200]}"
    return payload, None


def describe(payload):
    """One line about what came back, so the run is readable while it happens."""
    if "items" in payload or "data" in payload:
        if "items" in payload:
            volumes = payload.get("items") or []
            return f"{len(volumes)} volumes, totalItems {payload.get('totalItems')}"
        editions = ((payload.get("data") or {}).get("editions")) or []
        dated = sum(1 for edition in editions if edition.get("release_date"))
        return f"{len(editions)} editions, {dated} dated"
    return f"{len(json.dumps(payload))} bytes"


def tokens():
    """The two secrets, or the reason this cannot run."""
    token = os.environ.get(TOKEN_VARIABLE, "").strip()
    key = os.environ.get(KEY_VARIABLE, "").strip()
    missing = [
        name
        for name, value in ((TOKEN_VARIABLE, token), (KEY_VARIABLE, key))
        if not value
    ]
    return token, key, missing


def collect(rows, token, key, pace_seconds=HARDCOVER_PACE_SECONDS):
    """Fetch every row, then write them all: nothing lands unless all of it does."""
    replies = {}
    for row in rows:
        payload, problem = capture(row, token, key, pace_seconds)
        if problem:
            return None, f"{label(row)}: {problem}"
        replies[row["fixture"]] = payload
        print(f"  {label(row):<60} {describe(payload)}")
    return replies, None


def write(rows, replies):
    for row in rows:
        path = fixture_path(row["fixture"], row["source"])
        path.write_text(
            json.dumps(replies[row["fixture"]], indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {path.relative_to(ROOT)}")


def label(row):
    """A fixture named so that it is unambiguous which file is meant."""
    return f"{row['source']}/{row['fixture']}"


def plan(rows):
    """What each row will be asked, in the order it will be asked."""
    print(f"{len(RECORDINGS)} declared fixtures; {len(SKIPPED)} with no query at all.")
    print()
    for number, row in enumerate(rows, 1):
        request = sent_request(row)
        if row["source"] == "hardcover":
            variables = json.dumps(request["variables"])
            print(f"{number:>3}. {label(row):<60} Hardcover {variables}")
        else:
            print(f"{number:>3}. {label(row):<60} Google q={request['q']!r}")
            extra = {
                name: request[name]
                for name in ("langRestrict", "maxResults")
                if name in request
            }
            if extra:
                print(f"{'':>3}  {'':<60} {json.dumps(extra)}")


def select(named):
    """The rows a list of names asks for, and the names that match nothing.

    The two sources reuse fixture names - there is a
    `by-title-cragside.json` under each - so a bare name means every fixture with
    it and `hardcover/by-title-cragside.json` means the one. Both forms are
    accepted because recording all of them is the ordinary run and recording one is
    the ordinary experiment.
    """
    if not named:
        return list(RECORDINGS), []
    wanted = set(named)
    rows = [
        row
        for row in RECORDINGS
        if row["fixture"] in wanted or f"{row['source']}/{row['fixture']}" in wanted
    ]
    matched = {row["fixture"] for row in rows} | {label(row) for row in rows}
    return rows, sorted(wanted - matched)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Re-record the committed source fixtures against today's queries."
    )
    parser.add_argument(
        "fixture",
        nargs="*",
        help=(
            "fixtures to record, as `name.json` or `source/name.json`; all of them "
            "when none is named"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="show what would be recorded, and ask nothing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="do everything but write the files",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=HARDCOVER_PACE_SECONDS,
        metavar="SECONDS",
        help=(
            "seconds between Hardcover requests, to stay under its rate limit "
            f"(default {HARDCOVER_PACE_SECONDS:g}; Google is not paced)"
        ),
    )
    args = parser.parse_args(argv)

    rows, unknown = select(args.fixture)
    if unknown:
        parser.error(f"no declared recording for {', '.join(unknown)}")

    if args.list or args.dry_run:
        plan(rows)
        if args.dry_run:
            print("\ndry run: nothing was written and nothing was asked")
        return 0

    token, key, missing = tokens()
    if missing:
        print(f"set {' and '.join(missing)} first; see docs/recording-fixtures.md")
        return 2

    hardcover_rows = sum(1 for row in rows if row["source"] == "hardcover")
    print(f"Recording {len(rows)} fixtures against the shipped queries.")
    if hardcover_rows and args.pace > 0:
        print(
            f"Pacing Hardcover at {args.pace:g}s between requests "
            f"({hardcover_rows} of them, about "
            f"{hardcover_rows * args.pace / 60:.1f} minutes); "
            "a 429 is waited out and retried."
        )
    replies, problem = collect(rows, token, key, args.pace)
    if problem:
        print(f"\nREFUSING to write anything: {problem}")
        return 1
    print()
    write(rows, replies)
    print("\nNow run the tests: python -m unittest -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
