"""The Hardcover source: one exact-ISBN lookup, and nothing clever.

Hardcover keeps ISBNs on *editions*, not on books, so a lookup starts there and
walks to the work for the title, the authors and the series. The token comes
from a Docker secret and is never written to a log or an error message: this
module does no logging at all, and every message it raises has the token taken
back out of it.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SOURCE = "hardcover"
DEFAULT_URL = "https://api.hardcover.app/v1/graphql"
TIMEOUT_SECONDS = 30
USER_AGENT = "Colophon (+https://github.com/Cbow2018/colophon)"
REDACTED = "[token]"

# `books` has no ISBN column at all; the ISBNs are on the editions. Both forms
# are tried in one query so the caller need not know which one the file carried.
QUERY = """
query BookByIsbn($isbn: String!) {
  editions(
    where: {_or: [{isbn_13: {_eq: $isbn}}, {isbn_10: {_eq: $isbn}}]}
    limit: 1
  ) {
    isbn_13
    isbn_10
    title
    language { language code2 code3 }
    book {
      title
      contributions(where: {contribution: {_eq: "Author"}}, order_by: {id: asc}) {
        contribution
        author { name }
      }
      book_series {
        position
        details
        series { name }
      }
    }
  }
}
"""


class SourceError(Exception):
    """Hardcover could not answer: a bad key, an outage, or a reply we cannot read."""


@dataclass(frozen=True)
class SourceBook:
    """A book as a source describes it. Every value below came from that source."""

    source: str
    title: str | None
    authors: tuple
    series: str | None
    series_number: str | None
    language: str | None
    isbn: str | None


class Hardcover:
    """Looks a book up by its exact ISBN.

    `transport` is the seam the tests replay recorded replies through; left out,
    it posts to Hardcover over HTTPS.
    """

    def __init__(self, token, url=DEFAULT_URL, timeout=TIMEOUT_SECONDS, transport=None):
        self._token = token
        self._url = url
        self._timeout = timeout
        self._transport = transport or self._post

    @classmethod
    def from_secret_file(cls, path, **kwargs):
        """The source, or None when there is no token file to read.

        A missing or empty file means the user has not set Hardcover up, which
        is not an error: Colophon simply has no source to consult. Where that
        file lives is the config's business, so it is passed in.
        """
        secret = Path(path)
        try:
            token = secret.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise SourceError(f"could not read the Hardcover token file: {error}") from error
        return cls(token, **kwargs) if token else None

    def by_isbn(self, isbn):
        """The book carrying this ISBN, or None when Hardcover has no such edition."""
        isbn = str(isbn).strip()
        payload = self._ask({"query": QUERY, "variables": {"isbn": isbn}})
        editions = _dig(payload, "data", "editions")
        if editions is None:
            # An answer without the field we asked for is not an answer.
            raise SourceError("Hardcover's reply did not contain any editions")
        if not editions:
            return None
        return _as_book(editions[0], isbn)

    def _ask(self, question):
        request = json.dumps(question).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            status, reply = self._transport(self._url, headers, request)
        except SourceError:
            raise
        except Exception as error:
            raise SourceError(f"could not reach Hardcover: {self._without_token(error)}") from error

        if status in (401, 403):
            raise SourceError(f"Hardcover rejected the token (HTTP {status})")
        if status == 429:
            raise SourceError("Hardcover is rate limiting (HTTP 429)")
        if not 200 <= status < 300:
            raise SourceError(f"Hardcover answered HTTP {status}")

        try:
            payload = json.loads(reply)
        except (TypeError, ValueError) as error:
            raise SourceError(f"Hardcover's reply was not JSON: {error}") from error
        if not isinstance(payload, dict) or payload.get("errors"):
            raise SourceError(
                f"Hardcover refused the query: {self._without_token(_summarise(payload))}"
            )
        return payload

    def _post(self, url, headers, body):
        """The real transport: one POST, with whatever status came back."""
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def _without_token(self, text):
        """Anything on its way into a log or an error, with the token taken out."""
        text = str(text)
        return text.replace(self._token, REDACTED) if self._token else text


def _as_book(edition, isbn):
    """Turn one edition from the reply into a source record."""
    book = edition.get("book") or {}
    language = edition.get("language") or {}
    series, series_number = _series(book)
    return SourceBook(
        source=SOURCE,
        # The work's title is the book's name; an edition's title often repeats
        # the series and the subtitle, and is only used when the work has none.
        title=_text(book.get("title")) or _text(edition.get("title")),
        authors=tuple(_authors(book)),
        series=series,
        series_number=series_number,
        # A code is what an EPUB wants to be given back; the English name is a fallback.
        language=_text(language.get("code2")) or _text(language.get("language")),
        isbn=_text(edition.get("isbn_13")) or _text(edition.get("isbn_10")) or isbn,
    )


def _authors(book):
    """The people who wrote it, in the order Hardcover lists them.

    Hardcover puts everyone in `contributions` - translators and narrators
    included - so only the authors are taken. The query asks the source to
    filter; this filters again in case the reply is wider than the question.
    """
    names = []
    for contribution in book.get("contributions") or []:
        if contribution.get("contribution") != "Author":
            continue
        name = _text((contribution.get("author") or {}).get("name"))
        if name:
            names.append(name)
    return names


def _series(book):
    """The series the book belongs to, and the position it sits at in it."""
    for membership in book.get("book_series") or []:
        name = _text((membership.get("series") or {}).get("name"))
        if name:
            return name, _as_position(membership.get("position"))
    return None, None


def _as_position(value):
    """Positions are numbers in the schema: 6, not 6.0, and 1.5 stays 1.5."""
    if value is None:
        return None
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return _text(value)


def _text(value):
    text = "" if value is None else str(value).strip()
    return text or None


def _dig(payload, *keys):
    found = payload
    for key in keys:
        if not isinstance(found, dict):
            return None
        found = found.get(key)
    return found


def _summarise(payload):
    """The gist of a refusal, which never needs to be the whole reply."""
    if isinstance(payload, dict) and payload.get("errors"):
        return "; ".join(str(error.get("message")) for error in payload["errors"][:3])
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"])
    return "unexpected reply"
