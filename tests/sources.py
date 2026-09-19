"""A stand-in for Hardcover, so tests never need a key or a network."""

from colophon.hardcover import SourceBook
from tests.samplebooks import ISBN

# What Hardcover has for the ISBN in the sample book.
MATCH = SourceBook(
    source="hardcover",
    title="Cragside",
    authors=("LJ Ross",),
    series="DCI Ryan",
    series_number="6",
    language="en",
    isbn=ISBN,
)


class FakeSource:
    """A source that answers from a fixture, and remembers what it was asked."""

    def __init__(self, found=MATCH, error=None):
        self.found = found
        self.error = error
        self.asked = []

    def by_isbn(self, isbn):
        self.asked.append(isbn)
        if self.error is not None:
            raise self.error
        return self.found
