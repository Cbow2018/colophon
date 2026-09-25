"""One source, and what every source has in common.

A source is somewhere metadata can be looked up. It has a name it calls itself,
and it is asked two questions that every source answers the same way:

    by_isbn(isbn)                        -> a candidate, or None
    by_title(titles, language, author)   -> candidates, or []

`by_isbn` answers with a single candidate because an ISBN identifies one book,
and with None when that source has no such edition - which is a normal answer,
not a failure. `by_title` answers with every record it is willing to offer,
because a title identifies nothing on its own and comparing the records against
the file is the caller's job.

`SourceError` is the one failure type: a bad key, an outage, or a reply that
could not be read. It lives here rather than in any one source because the
corrector has to catch it whichever source raised it, and two classes with the
same name in two modules would not be caught by one `except` clause - a mistake
that is invisible until the moment a source actually fails.
"""

import http.client
import re
import socket
import ssl
import urllib.error
import urllib.request

from colophon.epub import is_cover

USER_AGENT = "Colophon (+https://github.com/Cbow2018/colophon)"
IMAGE_TIMEOUT_SECONDS = 30

# What a transport may raise that is the exchange's fault rather than ours: the
# socket's own errors, and `http.client`'s for a reply that could not be read as
# HTTP at all - a `BadStatusLine` for a server answering nonsense, which
# `urlopen` raises and which is *not* an `OSError`. Everything else is a bug in
# Colophon and is left to raise, rather than being reported as a source that
# could not be reached (CBO-78).
TRANSPORT_FAILURES = (OSError, http.client.HTTPException)

# The two kinds every failure is sorted into (CBO-78). A *temporary* failure is
# one asking again later is worth: an outage. Everything else is *held* - the
# user has to fix something and restart - so the kind decides what happens to a
# book, and is carried as data rather than read out of the message. The words
# live here because `LlmError` carries the same two, and one definition is what
# keeps the two failure types from drifting apart.
TEMPORARY = "temporary"
HELD = "held"

# The reasons shared by every failure of one class, in Colophon's own words. A
# reason is what a log line, the health file, the webhook and CBO-44's notice
# print, and none of those may carry the server's text: a reason is built from
# the status or the socket error, never from the reply (CBO-78).
REJECTED_KEY = "rejected the key"
UNREADABLE_REPLY = "unreadable reply"

# What a failure with nothing more specific to say is called, by kind: a held
# failure is a key or a configuration problem by definition (Q3), and a
# temporary one is an outage (Q24).
DEFAULT_REASONS = {TEMPORARY: "outage", HELD: "configuration problem"}

# Every cover failure says the same short thing. A cover is never held (CBO-44's
# D8), so only a log line reads this and the detail stays in the message.
COVER_FAILED = "the cover could not be fetched"

# A source genre string is sometimes a BISAC path (`Fantasy:Humour`) and
# sometimes a list (`Classics; Fantasy; Horror`), so both separators are split
# on. One definition, so what is asked about and what is cached cannot disagree
# about where one genre ends and the next begins.
_GENRE_SEPARATOR = re.compile(r"[:;]")

# A cover is a few tens of kilobytes. This is far above any real one and far
# below the point where holding it in memory matters, so it only ever catches a
# reply that is not a cover at all - an error page, or a redirect to a film.
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class SourceError(Exception):
    """A source could not answer: a bad key, an outage, or an unreadable reply.

    `kind` is `TEMPORARY` or `HELD`: whether the source will answer later, or
    whether someone has to fix something first. `reason` is the short phrase for
    the log line, the health file and the notice, in Colophon's own words - never
    the message, which may quote the server. `rejected` says whether the source
    refused the credential itself, which is one held failure among several: a
    configuration problem is held without being the key's fault, so the two are
    carried separately rather than inferred from each other. Where each kind
    leads is CBO-43's.
    """

    def __init__(self, message, kind=HELD, reason=None, rejected=False):
        super().__init__(message)
        self.kind = kind
        self.reason = reason or (REJECTED_KEY if rejected else DEFAULT_REASONS[kind])
        self.rejected = rejected


def status_failure(status, rejected=False):
    """What an HTTP refusal is: its kind, and the short reason for it.

    A server that is busy or out of time answers later, so a 408, a 429 and any
    5xx are temporary; everything else is the request or the credential being
    refused. The one status a caller reads differently is the LLM's 402, which
    `llm` adds.
    """
    kind = TEMPORARY if status in (408, 429) or status >= 500 else HELD
    if rejected:
        return HELD, REJECTED_KEY
    if status == 429:
        return kind, "rate limiting, HTTP 429"
    if kind == HELD and 400 <= status < 500:
        return kind, f"configuration problem, HTTP {status}"
    return kind, f"HTTP {status}"


def network_failure(error):
    """What a transport failure is: its kind, and the short reason for it.

    A timeout, a connection refused or reset, and a DNS failure all come right on
    their own. A TLS certificate failure does not, and neither does a reply that
    could not be read as HTTP at all - those are held, which is the safe way
    round, because a retry schedule cannot fix a configuration problem.
    `URLError` carries the socket's own exception in `reason`, and that is where
    the distinction really lives.
    """
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, TimeoutError):
        return TEMPORARY, "timeout"
    if isinstance(reason, ConnectionRefusedError):
        return TEMPORARY, "connection refused"
    if isinstance(reason, ConnectionError):
        return TEMPORARY, "connection reset"
    if isinstance(reason, socket.gaierror):
        return TEMPORARY, "DNS failure"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return HELD, "TLS certificate failure"
    return HELD, UNREADABLE_REPLY


def text(value):
    """A value from an API reply as text, or None when there is nothing there.

    Every source reads strings out of a JSON reply, where a field may be absent,
    null, empty, or whitespace: all four mean the same thing to us, which is that
    the source said nothing. `None` is how the rest of Colophon spells that, so
    that is what this hands back.
    """
    if value is None:
        return None
    found = str(value).strip()
    return found or None


def genre_parts(value):
    """One source's genre string as the genres inside it, in order, without empties.

    A source's own string is kept by whoever calls this, beside the parts: the
    parts are what is asked about and cached, and the whole string is the only
    record of what the source actually wrote.
    """
    return tuple(
        part.strip() for part in _GENRE_SEPARATOR.split(str(value)) if part.strip()
    )


def image(url, timeout=IMAGE_TIMEOUT_SECONDS, transport=None):
    """The image at this URL, or None when there is no URL to fetch.

    A source offers a cover as a URL, and this is the one place Colophon follows
    one. A cover that cannot be fetched is a `SourceError` rather than a
    `None`, because the two mean different things to a book: no URL at all is a
    source that has no cover for this book, while a URL that does not answer is
    a source that could not be asked - and the second one is worth saying out
    loud rather than passing over in silence.

    What comes back is accepted for one reason only, which is that its bytes are
    an image `epub.is_cover` knows. A `Content-Type` header is not a second
    opinion: it is whatever the server felt like saying, and a book should not
    take an image the writer will refuse because a header claimed otherwise.

    Every failure here is the temporary kind, whatever caused it: a cover is
    never held (CBO-44 D8). The book goes out without the image, the cover-only
    outage tag is CBO-43's and CBO-61 is what applies it, and the caller logs the
    line - so nothing waits on a picture and no container goes unhealthy for one.

    `transport` is the seam the tests replay recorded covers through, and it is
    handed the same `timeout` this was given; left out, this fetches over HTTP.
    """
    if not url:
        return None
    fetch = transport or _fetch
    try:
        status, body = fetch(str(url), {"User-Agent": USER_AGENT}, timeout)
    except SourceError:
        raise
    except TRANSPORT_FAILURES as error:
        raise SourceError(
            f"could not fetch the cover: {error}", TEMPORARY, COVER_FAILED
        ) from error

    if not 200 <= status < 300:
        raise SourceError(
            f"could not fetch the cover: it answered HTTP {status}",
            TEMPORARY,
            COVER_FAILED,
        )
    if not body:
        return None
    if len(body) > MAX_IMAGE_BYTES:
        raise SourceError(
            f"the cover is too large to be one ({len(body)} bytes); leaving the book alone",
            TEMPORARY,
            COVER_FAILED,
        )
    if not is_cover(body):
        raise SourceError("the cover was not an image", TEMPORARY, COVER_FAILED)
    return body


def _fetch(url, headers, timeout):
    """The real fetch: one GET, with whatever status and bytes came back."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def fetcher_for(timeout=IMAGE_TIMEOUT_SECONDS):
    """The real fetch, with its timeout bound, as the corrector calls it.

    The corrector asks for a cover by URL and nothing else, so the timeout is
    decided here rather than passed through every layer that does not care.
    """
    return lambda url: image(url, timeout=timeout)
