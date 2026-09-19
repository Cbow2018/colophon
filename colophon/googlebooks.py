"""The Google Books source: the ISBN lookup, and the title lookup for a book
that carries no ISBN.

Google's `/books/v1/volumes` is not a lookup service, it is a search engine, and
the difference shows in two places that `docs/research/cbo-37-google-books.md`
records from the live API. First, `isbn:` is a relevance query: asked about
`isbn:9781521748830` - the right ISBN with its check digit wrong - Google
answers 200 with the book carrying the *correct* number, and asked about
`isbn:9780000000000` it answers with three volumes carrying a different one. So
`by_isbn` reads the identifiers off every volume it is offered and keeps only
the ones that really carry the ISBN asked about. Without that, Colophon would
write another edition's ISBN into the file and report certainty while doing it.

Second, Google returns no series data for novels at all. `seriesInfo` is a
comics-and-collected-editions structure and is absent from every novel measured;
where the word "series" appears it is prose inside `description`. Nothing here
invents a series, and a book matched from Google Books has its title and authors
corrected and no series written.

The key travels as the `key` query parameter, because Google has no bearer
header. That makes the whole URL a secret, so no URL is ever logged or included
in an error message: every message this module raises has the key taken back out
of it.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from colophon.matching import Candidate
from colophon.sources import SourceError
from colophon.sources import text as _text

__all__ = ["SOURCE", "GoogleBooks"]

SOURCE = "google_books"
DEFAULT_URL = "https://www.googleapis.com/books/v1/volumes"
TIMEOUT_SECONDS = 30
USER_AGENT = "Colophon (+https://github.com/Cbow2018/colophon)"
REDACTED = "[key]"

# Only the parts a Candidate is built from: `description` alone is 500-1800
# characters per volume, and none of it is read here.
FIELDS = (
    "totalItems,items/id,items/volumeInfo/title,items/volumeInfo/authors,"
    "items/volumeInfo/language,items/volumeInfo/industryIdentifiers"
)

# How many volumes to ask for. Google's ceiling is 40 and it answers 400 above
# that; the default is 10, and a title-and-author search returns one or two.
MAX_RESULTS = 40

# A 400 or a 403 is Google refusing the key. It is the message that says so, not
# the status: an empty `q` and an out-of-range `maxResults` are 400 as well, and
# neither is anything the user has to go and fix.
_KEY_WORDS = ("api key", "keyinvalid", "key expired", "keyexpired", "not authorized")


class GoogleBooks:
    """Looks a book up by its exact ISBN, or by a cleaned title when it has none.

    `transport` is the seam the tests replay recorded replies through; left out,
    it fetches from Google over HTTPS.
    """

    # What this source calls itself, as its candidates do.
    name = SOURCE

    def __init__(self, key, url=DEFAULT_URL, timeout=TIMEOUT_SECONDS, transport=None):
        self._key = key
        self._url = url
        self._timeout = timeout
        self._transport = transport or self._get

    @classmethod
    def from_secret_file(cls, path, **kwargs):
        """The source, or None when there is no key file to read.

        Google gives a keyless caller no queries at all - the anonymous daily
        quota is zero - so a missing or empty key file means this source is
        simply not available, which the caller logs once and carries on from.
        """
        secret = Path(path)
        try:
            key = secret.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise SourceError(
                f"could not read the Google Books key file: {error}"
            ) from error
        return cls(key, **kwargs) if key else None

    def by_isbn(self, isbn):
        """The book carrying this ISBN, or None when Google has no such volume.

        Google answers a relevance query, so the reply may hold volumes that do
        not carry the ISBN at all. This keeps the ones that do and ignores the
        rest, which is what makes the ISBN path an exact match rather than a
        good guess.
        """
        wanted = _as_isbn(isbn)
        if not wanted:
            return None
        payload = self._ask(f"isbn:{isbn}")
        for volume in _volumes(payload):
            found = _candidate(volume)
            if wanted in _identifiers(volume):
                return found
        return None

    def by_title(self, titles, language=None, author=None):
        """Every volume matching this title, as candidates to score.

        One request, with the cleaned title and the author as server-side
        filters, because that is what makes the reply usable: the title alone
        returned 300 items for *Cragside*, most of them National Trust
        guidebooks, and `intitle:"Cragside" inauthor:"L.J. Ross"` returned the
        two right volumes. The author is matched by Google across punctuation,
        so a file spelling it `LJ Ross` still finds a record spelling it
        `L. J. Ross`.

        A source that has nothing to compare must not be offered, so a file with
        no author is asked about without the filter, and one with no language
        without the restriction.
        """
        titles = [str(title).strip() for title in titles if str(title).strip()]
        if not titles:
            return []
        payload = self._ask(
            _query(titles, language, author), language=language, max_results=MAX_RESULTS
        )
        return [_candidate(volume) for volume in _volumes(payload)]

    def _ask(self, query, language=None, max_results=None):
        params = {"q": query, "fields": FIELDS, "key": self._key}
        if max_results:
            params["maxResults"] = max_results
        # Google ignores `langRestrict` for many queries - asked for French, it
        # returned the English volumes - but it is the documented parameter, so
        # it is still sent, and the caller still checks nothing: the existing
        # design treats the language as a dial on the request rather than a veto
        # on the reply.
        if language:
            params["langRestrict"] = language
        url = f"{self._url}?{urllib.parse.urlencode(params)}"

        try:
            status, reply = self._transport(url, self._headers())
        except SourceError:
            raise
        except Exception as error:
            raise SourceError(
                f"could not reach Google Books: {self._without_key(error)}"
            ) from error
        return self._read(status, reply)

    def _read(self, status, reply):
        try:
            payload = json.loads(reply)
        except (TypeError, ValueError) as error:
            if not 200 <= status < 300:
                raise SourceError(*self._refusal(status, None)) from error
            raise SourceError(f"Google Books' reply was not JSON: {error}") from error

        if not 200 <= status < 300:
            raise SourceError(*self._refusal(status, payload))
        if not isinstance(payload, dict):
            raise SourceError("Google Books' reply was not what was asked for")
        if payload.get("error"):
            # A reply that carries an error is not an answer, whatever it came
            # with. It is judged as if it had failed, because it did.
            raise SourceError(*self._refusal(status, payload))
        return payload

    def _refusal(self, status, payload):
        """What to say about a refusal, and whether it was the key's fault.

        A spent daily quota is the one refusal that is not about the key and not
        about the query either: it resets, so it is an outage.
        """
        reason = _reason(payload) or "unexpected reply"
        if status == 429:
            return f"Google Books is rate limiting (HTTP {status}): {reason}", False
        if status in (400, 403) and _blames_the_key(reason):
            return f"Google Books rejected the key (HTTP {status}): {reason}", True
        return f"Google Books answered HTTP {status}: {reason}", False

    def _headers(self):
        return {"Accept": "application/json", "User-Agent": USER_AGENT}

    def _get(self, url, headers):
        """The real transport: one GET, with whatever status came back."""
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def _without_key(self, text):
        """Anything on its way into a log or an error, with the key taken out."""
        text = str(text)
        return text.replace(self._key, REDACTED) if self._key else text


def _query(titles, language, author):
    """The `q` Google is asked, with the filters that make the reply usable."""
    found = " OR ".join(f'intitle:"{_clean(title)}"' for title in titles)
    if author:
        found += f' inauthor:"{_clean(author)}"'
    return found


def _clean(text):
    """A quote inside a quoted search term would end the term early."""
    return str(text).replace('"', " ").strip()


def _volumes(payload):
    """The volumes in a reply. Not every reply has any: a 200 need not."""
    items = payload.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def _candidate(volume):
    """Turn one volume into a candidate, writing down only what Google knows.

    The series fields are left alone deliberately: Google has none for a novel,
    so nothing may be invented for it. The subtitle is left off the title
    because the work's title is what a file is matched on, and a source keeping
    its subtitle on the record is the case the comparison already handles.
    """
    info = volume.get("volumeInfo") or {}
    return Candidate(
        source=SOURCE,
        title=_text(info.get("title")),
        authors=tuple(
            name
            for name in (_text(author) for author in info.get("authors") or [])
            if name
        ),
        language=_text(info.get("language")),
        isbn=_preferred_isbn(_identifiers(volume)),
    )


def _identifiers(volume):
    """Every ISBN this volume carries, both forms, so either can be matched.

    One place reads Google's `industryIdentifiers`, so the ISBN a candidate is
    given and the ISBNs a lookup checks it against cannot disagree about how an
    identifier is spelt: `978-1-5217-4883-1` and `9781521748831` are one number.
    """
    info = volume.get("volumeInfo") or {}
    found = {
        _as_isbn(identifier.get("identifier"))
        for identifier in info.get("industryIdentifiers") or []
        if isinstance(identifier, dict)
    }
    return {isbn for isbn in found if isbn}


def _preferred_isbn(identifiers):
    """Which of a volume's ISBNs to write down: thirteen digits, then ten."""
    thirteen = [isbn for isbn in identifiers if len(isbn) == 13]
    tens = [isbn for isbn in identifiers if len(isbn) == 10]
    return (thirteen or tens or [None])[0]


def _as_isbn(value):
    """An ISBN as its digits, so the two ways of writing one compare equal."""
    if value is None:
        return None
    found = str(value).replace("-", "").replace(" ", "").strip()
    return found or None


def _reason(payload):
    """The gist of a refusal, which never needs to be the whole reply."""
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        if error.get("message"):
            return str(error["message"])
        errors = error.get("errors") or []
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("message") or errors[0].get("reason") or "")
    if isinstance(error, str):
        return error
    return None


def _blames_the_key(reason):
    """Whether a refusal is about the key, rather than about the query.

    Google answers 400 for a wrong key and for a malformed query alike, so the
    status alone does not say which. Every key refusal measured - a wrong key, a
    junk key, a truncated key - carried "API key not valid.", and the query
    mistakes carried `reason: required` and `reason: invalidParameter`.
    """
    lowered = str(reason or "").lower()
    return any(word in lowered for word in _KEY_WORDS)
