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

import urllib.error
import urllib.request

from colophon.epub import is_cover

USER_AGENT = "Colophon (+https://github.com/Cbow2018/colophon)"
IMAGE_TIMEOUT_SECONDS = 30

# A cover is a few tens of kilobytes. This is far above any real one and far
# below the point where holding it in memory matters, so it only ever catches a
# reply that is not a cover at all - an error page, or a redirect to a film.
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class SourceError(Exception):
    """A source could not answer: a bad key, an outage, or an unreadable reply.

    `rejected` says whether the source refused the credential itself, rather
    than being temporarily unable to answer. The two lead somewhere different -
    a rejected key holds books and marks the container unhealthy, an outage
    waits and retries - so the distinction is carried rather than flattened.
    The retry window itself is CBO-43's.
    """

    def __init__(self, message, rejected=False):
        super().__init__(message)
        self.rejected = rejected


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


def image(url, timeout=IMAGE_TIMEOUT_SECONDS, transport=None):
    """The image at this URL, or None when there is no URL to fetch.

    A source offers a cover as a URL, and this is the one place Colophon follows
    one. A cover that cannot be fetched is a `SourceError` rather than a
    `None`, because the two mean different things to a book: no URL at all is a
    source that has no cover for this book, while a URL that does not answer is
    a source that could not be asked - and the second one is worth saying out
    loud rather than passing over in silence.

    `transport` is the seam the tests replay recorded covers through; left out,
    this fetches over HTTP.
    """
    if not url:
        return None
    fetch = transport or _fetch
    try:
        status, body, content_type = fetch(str(url), {"User-Agent": USER_AGENT})
    except SourceError:
        raise
    except Exception as error:
        raise SourceError(f"could not fetch the cover: {error}") from error

    if not 200 <= status < 300:
        raise SourceError(f"could not fetch the cover: it answered HTTP {status}")
    if not body:
        return None
    if len(body) > MAX_IMAGE_BYTES:
        raise SourceError(
            f"the cover is too large to be one ({len(body)} bytes); leaving the book alone"
        )
    if not is_cover(body) and not str(content_type or "").startswith("image/"):
        raise SourceError("the cover was not an image")
    return body


def _fetch(url, headers, timeout=IMAGE_TIMEOUT_SECONDS):
    """The real fetch: one GET, with whatever status, bytes and type came back."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get("Content-Type")
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get("Content-Type")
