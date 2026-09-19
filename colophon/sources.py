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
