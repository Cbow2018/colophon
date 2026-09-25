"""Which query would produce each committed source fixture, as data.

The fixtures are the API's own bytes and stay that way: nothing about the request
is written inside a fixture, because `Replay` hands the body straight back to the
client and the fixture READMEs state that nothing inside them is changed. The
mapping belongs here instead, where the recorder reads it and the guard does too.

`RECORDINGS` is the whole of it: one row per fixture, naming the lookup and the
book it was made about. A fixture with no row is a fixture whose query nobody has
declared, which the fixture-query guard treats as a failure rather than as
permission to skip it.

The request is never spelled out by hand. `sent_request` builds it by running the
book through the shipped `GoogleBooks` or `Hardcover` client and reading the
request off the wire, so a query that changes in `colophon/` changes the
expectation here in the same commit, and the two cannot disagree.

`SKIPPED` names the fixtures that deliberately have no row, with the reason. That
is a different claim from a row: it says no shipped query produces this file at
all, rather than that this file is exempt from a query it should match.
"""

import json
import urllib.parse
from pathlib import Path

from colophon.googlebooks import GoogleBooks
from colophon.hardcover import Hardcover
from colophon.sources import SourceError

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = ROOT / "tests" / "fixtures"

# The books the fixtures were recorded about, as (title, author, language).
CRAGSIDE = ("Cragside", "L. J. Ross", "en")
BERWICK = ("Berwick", "L. J. Ross", "en")
BELSAY = ("Belsay", "L. J. Ross", "en")
THE_INFIRMARY = ("The Infirmary", "L. J. Ross", "en")
THE_INFIRMARY_REAGON = ("The Infirmary", "Carly Reagon", "en")
POE = ("The Masque of the Red Death", "Edgar Allan Poe", "en")
# The query CBO-37 recorded the empty reply with: a title nobody has, no author.
NOTHING = ("The Cragside Compendium of Nothing", None, "en")

# The ISBNs the ISBN-path fixtures were recorded about. `9789999999991` is a
# well-formed number that is no book's and `9780000000000` a nonsense one; both
# are here because the *reply* to a bad ISBN is what those fixtures hold.
CRAGSIDE_ISBN = "9781521748831"
CRAGSIDE_ONE_DIGIT_OFF = "9781521748830"
UNRELATED_ISBN = "9780000000000"
NO_EDITION_ISBN = "9789999999991"
NORMAL_PEOPLE_ISBN = "9780571334650"
MISTBORN_ISBN = "9780765311788"
THE_HOBBIT_ISBN = "9780007458424"
# *The Infirmary*'s print Edition. It stops naming the Audible Studios on
# Brilliance ISBN, `9781799729945`, which the ticket was raised about: that
# Edition is an Audio Edition and is no longer offered as a candidate at all
# (CBO-90), so an ISBN-path recording made against it answers nothing.
THE_INFIRMARY_ISBN = "9781792780844"
BERWICK_ISBN = "9781529978940"
PYRAMIDS_ISBN = "9780575064843"
THE_TRIAL_ISBN = "9781529196382"
GENRES_NO_EDITION_ISBN = "9781473225374"

# One row per fixture a shipped query produces. The order is the order the
# re-record runs in and the order `tools/record-fixtures.py --list` prints.
#
# Two pairs of rows declare the same request, so a re-record writes identical
# bytes to four files: the Google Cragside title pair and the Google Cragside ISBN
# pair, each differing only in that the mask widened between them. Both files of a
# pair are read by name, so neither is dropped; whether a pair should become one
# file is a decision nobody has taken.
RECORDINGS = (
    # CBO-68's own files first: these are the five Hardcover title replies whose
    # missing release_date is the measurement CBO-68's decision 4 was waiting on.
    {
        "source": "hardcover",
        "fixture": "by-title-cragside.json",
        "lookup": "title",
        "book": CRAGSIDE,
    },
    {
        "source": "hardcover",
        "fixture": "by-title-cragside-other-fields.json",
        "lookup": "title",
        "book": CRAGSIDE,
    },
    {
        "source": "hardcover",
        "fixture": "by-title-berwick.json",
        "lookup": "title",
        "book": BERWICK,
    },
    {
        "source": "hardcover",
        "fixture": "by-title-belsay.json",
        "lookup": "title",
        "book": BELSAY,
    },
    {
        "source": "hardcover",
        "fixture": "by-title-the-infirmary.json",
        "lookup": "title",
        "book": THE_INFIRMARY,
    },
    # CBO-69's reproduction, and the file whose re-record can destroy a case:
    # hand-made/poe-core-cases.json is what makes that safe.
    {
        "source": "googlebooks",
        "fixture": "by-title-poe.json",
        "lookup": "title",
        "book": POE,
    },
    # CBO-68 D19: the shipped configuration could not be measured for Poe, because
    # no Hardcover reply existed for this request. The request carries no author,
    # so it is byte-identical to the Ross title request.
    {
        "source": "hardcover",
        "fixture": "by-title-poe.json",
        "lookup": "title",
        "book": POE,
    },
    # The rest of the Google title path.
    {
        "source": "googlebooks",
        "fixture": "by-title-cragside.json",
        "lookup": "title",
        "book": CRAGSIDE,
    },
    {
        "source": "googlebooks",
        "fixture": "by-title-cragside-other-fields.json",
        "lookup": "title",
        "book": CRAGSIDE,
    },
    {
        "source": "googlebooks",
        "fixture": "by-title-berwick.json",
        "lookup": "title",
        "book": BERWICK,
    },
    {
        "source": "googlebooks",
        "fixture": "by-title-belsay.json",
        "lookup": "title",
        "book": BELSAY,
    },
    {
        "source": "googlebooks",
        "fixture": "by-title-the-infirmary.json",
        "lookup": "title",
        "book": THE_INFIRMARY,
    },
    {
        "source": "googlebooks",
        "fixture": "by-title-the-infirmary-reagon.json",
        "lookup": "title",
        "book": THE_INFIRMARY_REAGON,
    },
    # The empty reply to a title Google does not have. It was recorded unmasked,
    # so it carried a `kind` key and 53 bytes; the shipped mask returns
    # `{"totalItems": 0}` and 17, and no test reads `kind`. CBO-39's relay test
    # replays this file, and what it needs is an empty answer, not those two keys.
    {
        "source": "googlebooks",
        "fixture": "by-title-nothing.json",
        "lookup": "title",
        "book": NOTHING,
    },
    # The Google ISBN path.
    {
        "source": "googlebooks",
        "fixture": "by-isbn-cragside.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "googlebooks",
        "fixture": "by-isbn-cragside-other-fields.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "googlebooks",
        "fixture": "by-isbn-cragside-authors.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "googlebooks",
        "fixture": "isbn-cragside-categories.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "googlebooks",
        "fixture": "by-isbn-one-digit-off.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ONE_DIGIT_OFF,
    },
    {
        "source": "googlebooks",
        "fixture": "by-isbn-unrelated.json",
        "lookup": "isbn",
        "isbn": UNRELATED_ISBN,
    },
    # The empty reply to an ISBN no book carries. The same 53-to-17 change as
    # `by-title-nothing.json` above, for the same reason.
    {
        "source": "googlebooks",
        "fixture": "by-isbn-no-edition.json",
        "lookup": "isbn",
        "isbn": NO_EDITION_ISBN,
    },
    # The Hardcover ISBN path.
    {
        "source": "hardcover",
        "fixture": "by-isbn-found.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-cragside-edition.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-9781521748831-genres.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-cragside-authors.json",
        "lookup": "isbn",
        "isbn": CRAGSIDE_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-no-series.json",
        "lookup": "isbn",
        "isbn": NORMAL_PEOPLE_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-two-series.json",
        "lookup": "isbn",
        "isbn": MISTBORN_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-9780575064843-packed-genres.json",
        "lookup": "isbn",
        "isbn": PYRAMIDS_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-9781529196382-packed-genres.json",
        "lookup": "isbn",
        "isbn": THE_TRIAL_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-9781529978940-genres.json",
        "lookup": "isbn",
        "isbn": BERWICK_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-berwick-authors.json",
        "lookup": "isbn",
        "isbn": BERWICK_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-9781792780844-genres.json",
        "lookup": "isbn",
        "isbn": THE_INFIRMARY_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-edition-title.json",
        "lookup": "isbn",
        "isbn": THE_HOBBIT_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-isbn-9781473225374-genres.json",
        "lookup": "isbn",
        "isbn": GENRES_NO_EDITION_ISBN,
    },
    {
        "source": "hardcover",
        "fixture": "by-title-the-infirmary-other-fields.json",
        "lookup": "title",
        "book": THE_INFIRMARY,
    },
)

# The fixtures no shipped query produces, and why. Anything here that *is* a
# reply to a shipped query belongs in `RECORDINGS` instead.
#
# `by-isbn-two-series.json` was expected to need a third category — a reply to a
# shipped query recorded deliberately off-spec — and does not. Asked with the
# shipped `order_by`, Hardcover returns the featured series first anyway, so the
# recording was never off-spec and is an ordinary row in `RECORDINGS`.
SKIPPED = {
    "hardcover/author-lj-ross.json": (
        "recorded against the `authors` root field, which no shipped query has"
    ),
    "hardcover/authors-spelling-variants.json": (
        "recorded against the `authors` root field, which no shipped query has"
    ),
    "hardcover/works-good-omens-authors.json": (
        "recorded against the `books` root field, which no shipped query has"
    ),
    "hardcover/nothing-found.json": (
        "the empty reply to an ISBN no edition carries; re-recording it answers "
        "the same 44 bytes"
    ),
    "hardcover/by-title-nothing-found.json": (
        "the empty reply to a title Hardcover does not have; re-recording it "
        "answers the same 44 bytes"
    ),
    "googlebooks/error-key-rejected.json": (
        "a 400 from a deliberately wrong key, which a re-record cannot send"
    ),
    "googlebooks/error-max-results-too-high.json": (
        "a 400 from a deliberately out-of-range maxResults, which the shipped "
        "client cannot send"
    ),
    "googlebooks/error-missing-query.json": (
        "a 400 from a deliberately missing q, which the shipped client cannot send"
    ),
    "googlebooks/hand-made/poe-core-cases.json": (
        "hand-made: a frozen case, never re-recorded"
    ),
    "googlebooks/hand-made/no-categories.json": (
        "hand-made: the CBO-38-era ISBN reply, from before the mask asked for "
        "categories, freezing what a volume with no categories answers"
    ),
    "hardcover/hand-made/work-without-title.json": (
        "hand-made: a frozen case, never re-recorded"
    ),
    "hardcover/hand-made/wider-than-the-question.json": (
        "hand-made: a frozen case, never re-recorded"
    ),
    "hardcover/hand-made/sparse-isbn-reply.json": (
        "hand-made: the pre-CBO-38 ISBN reply, freezing what a sparse reply "
        "answers for the ids, the tags, the publisher and the cover"
    ),
    "hardcover/hand-made/cbo-38-without-tags.json": (
        "hand-made: the CBO-38-era title reply, from before CBO-42 asked for "
        "cached_tags"
    ),
    "hardcover/hand-made/no-series.json": (
        "hand-made: the pre-CBO-38 ISBN reply for a standalone book, freezing "
        "that a book in no series answers no series"
    ),
    "hardcover/hand-made/two-series-featured-last.json": (
        "hand-made: a reply whose featured series is last, freezing that the "
        "client picks it out by the flag rather than by taking the first row"
    ),
    "hardcover/hand-made/audio-edition-earliest.json": (
        "hand-made: the CBO-90 case, an Edition the source states is Audio dated "
        "earliest; no live reply labels anything Audio"
    ),
}

# Where a fixture of each source lives, under `tests/fixtures/`.
SOURCE_DIRECTORY = {"googlebooks": "googlebooks", "hardcover": "hardcover"}


def fixture_path(fixture, source):
    """The file `RECORDINGS` declares this fixture to be, under `tests/fixtures/`."""
    return FIXTURE_ROOT / SOURCE_DIRECTORY[source] / fixture


def sent_request(row, token="TOKEN", key="KEY"):
    """The request the shipped client sends for this fixture, as data.

    The client is the real one, with a transport that records the request and
    hands back an empty 200: what comes back is the URL Google would be asked, as
    parsed query parameters with the key taken out, or the JSON body Hardcover
    would be posted. Nothing here contacts the network, and the empty reply is
    never read, because the request is what this is for.
    """
    captured = {}

    def capture(*args):
        captured["args"] = args
        return 200, b"{}"

    if row["source"] == "googlebooks":
        source = GoogleBooks(key, transport=capture)
    else:
        source = Hardcover(token, transport=capture)

    try:
        if row["lookup"] == "title":
            title, author, language = row["book"]
            source.by_title([title], language, author)
        else:
            source.by_isbn(row["isbn"])
    except SourceError:
        # An empty reply is not an answer, which is fine: the request was made
        # and captured before the client gave up on it.
        pass

    if row["source"] == "googlebooks":
        url = captured["args"][0]
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return {name: values[0] for name, values in params.items() if name != "key"}
    return json.loads(captured["args"][2])


def declarations():
    """Every fixture in the corpus, with the row that declares it or the reason none does.

    Yields `(source, fixture, row, reason)`, where exactly one of `row` and
    `reason` is set. The corpus is the directory listing, so a fixture added
    without a declaration shows up here rather than going unnoticed, and a
    `SKIPPED` entry naming a file that no longer exists is not reached at all.
    """
    for source, directory in SOURCE_DIRECTORY.items():
        for path in sorted((FIXTURE_ROOT / directory).rglob("*.json")):
            relative = path.relative_to(FIXTURE_ROOT / directory).as_posix()
            key = f"{directory}/{relative}"
            row = next(
                (
                    row
                    for row in RECORDINGS
                    if row["source"] == source and row["fixture"] == relative
                ),
                None,
            )
            yield source, relative, row, None if row is not None else SKIPPED.get(key)
