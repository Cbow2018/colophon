"""A stand-in for Hardcover, so tests never need a key or a network.

The title candidates below are what the recorded replies in
`tests/fixtures/hardcover/by-title-*.json` really say, so a test can drive the
corrector without going through the client's parsing of a reply.
"""

import json
from pathlib import Path

from colophon.hardcover import SOURCE
from colophon.matching import Candidate
from colophon.sources import SourceError
from tests.samplebooks import ISBN

RECORDED = Path(__file__).parent / "fixtures" / "hardcover"


def _recorded(name, path):
    """A value out of a recording, so a stand-in cannot drift from the reply."""
    payload = json.loads((RECORDED / name).read_text(encoding="utf-8"))
    found = payload
    for step in path:
        found = found[step]
    return found


# The real Cragside edition's blurb and cover, read out of the recording rather
# than retyped, so a stand-in and the reply it stands for cannot disagree. The
# blurb carries the source's own `ufffd` for the `é` in `fiancée`.
CRAGSIDE_BLURB = _recorded(
    "by-isbn-cragside-edition.json", ["data", "editions", 0, "book", "description"]
)
CRAGSIDE_COVER = _recorded(
    "by-isbn-cragside-edition.json", ["data", "editions", 0, "image", "url"]
)

# What Hardcover has for the ISBN in the sample book.
MATCH = Candidate(
    source=SOURCE,
    title="Cragside",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="6",
    language="en",
    isbn=ISBN,
    description=CRAGSIDE_BLURB,
    publisher="Independently Published",
    date="2017-07-07",
    cover=CRAGSIDE_COVER,
)

# The same record from a source that offers no cover, which is what most tests
# want. A candidate carrying a cover URL makes the corrector fetch it, and a
# test that fetches an image over the network fails when the network does -
# which is exactly what one of these tests used to do. `MATCH` is the one with
# the cover, for the tests that are about covers.
NO_COVER_MATCH = Candidate(
    source=SOURCE,
    title="Cragside",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="6",
    language="en",
    isbn=ISBN,
    description=CRAGSIDE_BLURB,
    publisher="Independently Published",
    date="2017-07-07",
)


def no_network(url):
    """A cover fetch that fails loudly, for a test that must not reach out.

    A test that does not mean to fetch a cover still should not be able to: the
    failure this raises is caught by the corrector and logged, so the test sees
    a book corrected without a cover rather than a test that hangs on DNS.
    """
    raise SourceError(f"a test tried to fetch {url} from the network")


# What Hardcover has for the three books whose files carry no ISBN. Belsay is
# #23 on the record, which the file's title never says.
CRAGSIDE_CANDIDATE = Candidate(
    source=SOURCE,
    title="Cragside",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="6",
    language="en",
)
BERWICK_CANDIDATE = Candidate(
    source=SOURCE,
    title="Berwick",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="24",
    language="en",
)
BELSAY_CANDIDATE = Candidate(
    source=SOURCE,
    title="Belsay",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="23",
    language="en",
)
# The lookalike this ticket names: the same author, a different book of hers.
THE_INFIRMARY_CANDIDATE = Candidate(
    source=SOURCE,
    title="The Infirmary",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="11",
    language="en",
)
# The real book of that name, by someone else, whose title matches exactly.
ANOTHER_INFIRMARY = Candidate(
    source=SOURCE, title="The Infirmary", authors=("Carly Reagon",), language="en"
)
# A book whose record keeps the subtitle the file's cleaning took off.
SAPIENS_CANDIDATE = Candidate(
    source=SOURCE,
    title="Sapiens: A Brief History of Humankind",
    authors=("Yuval Noah Harari",),
    language="en",
)


class FakeSource:
    """A source that answers from a fixture, and remembers what it was asked.

    `by_title` answers with the candidates it was given, or with a source
    problem when the test wants one; a test that wants the source to be asked
    about a title and nothing else passes `found=None` for the ISBN path.

    `name` is what the source calls itself, as a real source's candidates do:
    the priority list is made of sources that must be distinguishable in a log
    line, so a stand-in has to be distinguishable too.
    """

    def __init__(
        self,
        found=NO_COVER_MATCH,
        error=None,
        candidates=(),
        title_error=None,
        name=SOURCE,
    ):
        self.name = name
        self.found = found
        self.error = error
        self.candidates = list(candidates)
        self.title_error = title_error
        self.asked = []
        self.asked_titles = []
        self.asked_languages = []
        self.asked_authors = []

    def by_isbn(self, isbn):
        self.asked.append(isbn)
        if self.error is not None:
            raise self.error
        return self.found

    def by_title(self, titles, language=None, author=None):
        self.asked_titles.append(list(titles))
        self.asked_languages.append(language)
        self.asked_authors.append(author)
        if self.title_error is not None:
            raise self.title_error
        return list(self.candidates)
