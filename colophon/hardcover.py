"""The Hardcover source: an exact ISBN lookup, and a title lookup for the books
that carry no ISBN.

Hardcover keeps ISBNs on *editions*, not on books, so a lookup starts there and
walks to the work for the title, the authors and the series. The token comes
from a Docker secret and is never written to a log or an error message: this
module does no logging at all, and every message it raises has the token taken
back out of it.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

from colophon.matching import Candidate
from colophon.sources import SourceError
from colophon.sources import text as _text

# `SourceError` is imported from `colophon.sources` for this module's own use and
# deliberately not re-exported: a caller wanting the failure type imports it from
# where it is defined, so there is only ever one of it to catch. See the note in
# `colophon/sources.py` about what two classes with one name cost.
__all__ = ["SOURCE", "Hardcover"]

SOURCE = "hardcover"
DEFAULT_URL = "https://api.hardcover.app/v1/graphql"
TIMEOUT_SECONDS = 30
USER_AGENT = "Colophon (+https://github.com/Cbow2018/colophon)"
REDACTED = "[token]"

# `books` has no ISBN column at all; the ISBNs are on the editions. Both forms
# are tried in one query so the caller need not know which one the file carried.
#
# Which fields live where is the schema's, not a choice: the blurb and the
# release date are on the work, the publisher, the ISBN, the language and the
# cover's own image are on the edition, and `image` is on both. Every one of
# them is asked for here, and `_candidate` is the one place that decides what
# the pair of them means.
QUERY = """
query BookByIsbn($isbn: String!) {
  editions(
    where: {_or: [{isbn_13: {_eq: $isbn}}, {isbn_10: {_eq: $isbn}}]}
    limit: 1
  ) {
    isbn_13
    isbn_10
    title
    publisher { name }
    release_date
    image { url }
    language { language code2 code3 }
    book {
      title
      description
      release_date
      image { url }
      contributions(where: {contribution: {_eq: "Author"}}, order_by: {id: asc}) {
        contribution
        author { name }
      }
      book_series(order_by: [{featured: desc}, {position: asc}]) {
        featured
        position
        series { name }
      }
    }
  }
}
"""


# The same, for a book whose file carries no ISBN: ask about the cleaned title
# of the work, every edition of it coming back. `_in` is permitted on
# `books.title` where `_ilike` and the regex operators are refused, and `_eq`
# is case-sensitive, so the title has to be spelt the way Hardcover spells it.
# `_eq` on an author's name needs the full name as Hardcover writes it, which
# is why authors are compared here rather than filtered for on the server.
#
# The two placeholders are the language filter and the matching variable
# declaration, and they are the only things that differ between the two forms:
# `code2` is not nullable, so `{code2: {_eq: null}}` is refused outright rather
# than matching everything, and a file that does not say what language it is
# written in has to be asked about without one.
_TITLE_QUERY = """
query BooksByTitle($titles: [String!]!%s) {
  editions(
    where: {
      book: {title: {_in: $titles}}
      %s
    }
  ) {
    title
    publisher { name }
    release_date
    image { url }
    language { language code2 code3 }
    book {
      id
      title
      description
      release_date
      image { url }
      contributions(where: {contribution: {_eq: "Author"}}, order_by: {id: asc}) {
        contribution
        author { name }
      }
      book_series(order_by: [{featured: desc}, {position: asc}]) {
        featured
        position
        series { name }
      }
    }
  }
}
"""

# The query per language length. Every caller means the two-letter one, which
# is what most files say; a three-letter tag needs the other column.
TITLE_QUERY = _TITLE_QUERY % (", $language: String!", "language: {code2: {_eq: $language}}")
_TITLE_QUERY_BY_LENGTH = {
    2: TITLE_QUERY,
    3: _TITLE_QUERY % (", $language: String!", "language: {code3: {_eq: $language}}"),
}
_TITLE_QUERY_ANY_LANGUAGE = _TITLE_QUERY % ("", "")


class Hardcover:
    """Looks a book up by its exact ISBN, or by a cleaned title when it has none.

    `transport` is the seam the tests replay recorded replies through; left out,
    it posts to Hardcover over HTTPS.

    Both lookups answer with `Candidate`s, because both are records a source
    offered of a book and the caller writes them the same way. `by_isbn` offers
    at most one, since an ISBN identifies an edition and so a book; `by_title`
    offers every work carrying the title, because a title identifies nothing on
    its own and comparing them against the file is the caller's job.
    """

    # What this source calls itself, as its candidates do.
    name = SOURCE

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
        return cls(_without_bearer(token), **kwargs) if token else None

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
        return _candidate(editions[0], isbn)

    def by_title(self, titles, language=None, author=None):
        """Every work whose title matches one of these, as candidates to score.

        A title the API does not spell exactly gets no candidates at all, so
        the caller may pass more than one cleaned form of the file's title and
        this asks about them all in one request. The language the file is
        written in is the language asked for, so nothing translated is ever
        offered; a file that names no language is asked about without one.

        `author` is accepted for the sake of the sources interface and is not
        used: Hardcover's `_eq` on an author's name needs the full name spelt
        the way Hardcover writes it, which a file rarely is, so filtering on the
        server would throw away the records worth comparing. The authors are
        compared here instead, in `matching`.
        """
        titles = [str(title).strip() for title in titles if str(title).strip()]
        if not titles:
            return []
        language = str(language).strip() if language else ""
        if language:
            # Which column holds it depends on how long the tag is: a two-letter
            # code is ISO 639-1, a three-letter one is 639-2.
            query = _TITLE_QUERY_BY_LENGTH.get(len(language), TITLE_QUERY)
            variables = {"titles": titles, "language": language}
        else:
            query = _TITLE_QUERY_ANY_LANGUAGE
            variables = {"titles": titles}
        payload = self._ask({"query": query, "variables": variables})
        editions = _dig(payload, "data", "editions")
        if editions is None:
            # An answer without the field we asked for is not an answer.
            raise SourceError("Hardcover's reply did not contain any editions")
        return _candidates(editions)

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


def _candidate(edition, isbn=None):
    """Turn one edition from the reply into a candidate for the work behind it.

    The work is where the title, the authors, the series and the blurb live; the
    edition only carries the language, the publisher, its own release date and,
    sometimes, an ISBN. Both lookups read a reply through here, so there is one
    place that decides what a reply means.
    """
    book = edition.get("book") or {}
    language = edition.get("language") or {}
    series, series_number = _series(book)
    return Candidate(
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
        # The blurb belongs to the work, so every edition of it carries the same
        # one. The publisher and the date of the edition are the edition's, and
        # the work's date is only used when the edition does not give one.
        description=_text(book.get("description")),
        publisher=_text((edition.get("publisher") or {}).get("name")),
        date=_text(edition.get("release_date")) or _text(book.get("release_date")),
        # The edition's own cover, and the work's only when the edition has none.
        cover=_image(edition) or _image(book),
    )


def _image(item):
    """The cover URL an edition or a work carries, if it carries one."""
    return _text((item.get("image") or {}).get("url"))


def _candidates(editions):
    """Turn a title reply into one candidate per work, in the order it came back.

    The reply is a list of editions, and one work usually has several, so the
    first edition of a work is kept and the rest are dropped: the title, the
    authors and the series are all on the work, and a second edition would only
    offer the same book twice. The ISBN comes from the edition that matched,
    which is the only place Hardcover keeps one.
    """
    candidates = []
    seen = set()
    for position, edition in enumerate(editions):
        # A work whose id the reply omitted cannot be recognised twice over, so
        # it is left as its own candidate rather than mistaken for another.
        identity = (edition.get("book") or {}).get("id")
        if identity is None:
            identity = f"unnamed-{position}"
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(_candidate(edition))
    return candidates


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
    """The series Hardcover marks as featured, and the book's place in it.

    A book can sit in several series at once - a saga, a universe, a trilogy of
    that saga - and Hardcover marks the one it counts as the book's own. The
    query asks for that one first, and this picks it out again, so a source
    that ever ignored the ordering cannot quietly pick the wrong series.
    """
    memberships = [
        membership
        for membership in book.get("book_series") or []
        if _text((membership.get("series") or {}).get("name"))
    ]
    if not memberships:
        return None, None

    featured = [membership for membership in memberships if membership.get("featured")]
    chosen = (featured or memberships)[0]
    return (
        _text((chosen.get("series") or {}).get("name")),
        _as_position(chosen.get("position")),
    )


def _as_position(value):
    """Positions are numbers in the schema: 6, not 6.0, and 1.5 stays 1.5."""
    if value is None:
        return None
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return _text(value)


def _without_bearer(token):
    """A token copied whole from Hardcover's settings page carries its own prefix."""
    prefix = "bearer "
    if token[: len(prefix)].lower() == prefix:
        return token[len(prefix) :].strip()
    return token


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
