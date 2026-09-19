"""A stand-in for Hardcover, so tests never need a key or a network.

The title candidates below are what the recorded replies in
`tests/fixtures/hardcover/by-title-*.json` really say, so a test can drive the
corrector without going through the client's parsing of a reply.
"""

from colophon.hardcover import SOURCE
from colophon.matching import Candidate
from tests.samplebooks import ISBN

# What Hardcover has for the ISBN in the sample book.
MATCH = Candidate(
    source=SOURCE,
    title="Cragside",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="6",
    language="en",
    isbn=ISBN,
)

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
        self, found=MATCH, error=None, candidates=(), title_error=None, name=SOURCE
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
