"""Cleaning a file's title, and comparing a candidate against the file.

A book with no ISBN is matched on its title and its author. Both sides of that
comparison are messy in their own way, so this module does the whole
comparison: it cleans the file's title down to what a source would call the
book, normalises both sides' spelling for comparison, and turns the comparison
into the confidence the pipeline applies at 0.85.

Nothing here changes a value that gets written. Every normalisation is for
comparison only, and the written values stay exactly as the source spells them.
"""

import re
from dataclasses import dataclass

# How much of the confidence each half of the comparison carries. The weights
# are what make a title match on its own insufficient: even a perfect title
# scores 0.6, well under the 0.85 the pipeline applies, so a book is only ever
# accepted when its author agrees too. The evidence is in
# `docs/research/cbo-36-title-matching.md`.
TITLE_WEIGHT = 0.6
AUTHOR_WEIGHT = 0.4

EXACT_TITLE = 1.0
CONTAINED_TITLE = 0.9
NO_TITLE = 0.0
MATCHING_AUTHOR = 1.0
NO_AUTHOR = 0.0

# A third signal, once the first two have been weighed. The file's title often
# carries its series position, and that is the one fact about the book the
# title has that the source keeps elsewhere. Agreement is a small nudge up; two
# flatly different positions are a doubt, worth less than the nudge, because a
# source's numbering against a publisher's is the weakest of the three signals
# and must not overrule a title and an author that both agree exactly. Either
# side saying nothing is the usual case and counts for nothing.
SERIES_UNKNOWN = 0.0
SERIES_DISAGREEMENT = -0.1
SERIES_CONFIRMED = 0.05

# The most a candidate can score while agreeing on only one of the two halves,
# or on neither. Under the 0.85 the pipeline applies, with room for the series
# nudge above it, so that the arithmetic and `agrees` always say the same thing.
NO_AGREEMENT_CEILING = 0.7

# `(The DCI Ryan Mysteries Book 6)` and its relatives. The name is only there
# to be read by a human; the number is the part worth having.
_SERIES_BRACKET = re.compile(
    r"\s*\((?P<series>[^()]*?)\s*\b(?:book|volume|vol\.?)\s*(?P<number>\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE,
)
# A title and its subtitle, as a bookshop writes them.
_SUBTITLE = re.compile(r"\s*:\s+")
# Subtitles that say what kind of book this is rather than naming it.
_GENERIC_SUBTITLE = re.compile(
    r"\b(mystery|mysteries|novel|thriller|story|stories|romance|crime|saga|detective)\b",
    re.IGNORECASE,
)
_WORDS = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class CleanedTitle:
    """A file's title, as much as a source needs to be asked about it.

    `search` is what gets asked about. `also` is the same title with the
    subtitle left on, for the source that keeps the subtitle on its own record;
    it is None when the subtitle was never taken off, because then the two are
    one title. `series_number` is the position the file's own title claimed,
    which the comparison uses as a third signal.
    """

    search: str
    also: str | None = None
    series: str | None = None
    series_number: str | None = None


@dataclass(frozen=True)
class FileBook:
    """What the file says about itself, for the comparison's half of the work."""

    title: str
    authors: tuple = ()
    language: str | None = None


@dataclass(frozen=True)
class Candidate:
    """One book a source offered, as the source describes it.

    `source` names where it came from, so a candidate can be written into a
    file without anything else having to remember who offered it.
    """

    title: str | None
    authors: tuple = ()
    series: str | None = None
    series_number: str | None = None
    language: str | None = None
    isbn: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class Match:
    """One candidate measured against the file, and what came of the measuring.

    `confidence` is the number the pipeline applies its 0.85 threshold to, and
    `agrees` says whether the comparison found anything to go on at all: the
    titles have something in common and so do the authors. A candidate that
    does not agree is not an explanation of this file whatever the number says,
    which is why its confidence is held under `NO_AGREEMENT_CEILING`: the two
    always tell the same story.

    `candidate` is the book this is a measurement of, so a caller never has to
    carry the two around separately. The two reasons say why each half scored
    what it did, so a book that was passed over can say what was wrong with the
    best explanation of it.
    """

    candidate: Candidate
    confidence: float
    title_score: float
    author_score: float
    title_reason: str
    author_reason: str

    @property
    def agrees(self):
        """Whether the comparison found anything to go on at all.

        Derived from the two scores rather than stored, so a candidate that
        agrees on one half alone can never be reported as one that agrees on
        both - which is also why `score_candidate` holds such a candidate's
        confidence under `NO_AGREEMENT_CEILING`.
        """
        return self.title_score > 0.0 and self.author_score > 0.0

    @property
    def why(self):
        """What was wrong with this candidate, for a log line about a near miss."""
        return f"{self.title_reason}; {self.author_reason}"


def clean_title(title):
    """Take the series bracket and the subtitle off a title.

    The series number in the bracket is captured rather than thrown away,
    because it is the one fact about the book the title carries that a source
    keeps elsewhere. The cleaned title is what gets asked about: `books.title`
    holds the clean work title, so a title with the subtitle or the bracket
    still on it matches nothing at all. What the subtitle was taken off *from*
    is kept as `also`, because a source is free to have kept it.
    """
    text = _squeeze(str(title or ""))
    if not text:
        return CleanedTitle(search="")

    series = None
    series_number = None
    bracket = _SERIES_BRACKET.search(text)
    if bracket:
        series = _squeeze(bracket.group("series")) or None
        series_number = f"{float(bracket.group('number')):g}"
        text = _squeeze(text[: bracket.start()] + " " + text[bracket.end() :])

    without_subtitle = _split_subtitle(text)
    return CleanedTitle(
        search=without_subtitle,
        also=text if without_subtitle != text else None,
        series=series,
        series_number=series_number,
    )


def search_titles(title):
    """Every title to ask about, cleaned first, and None when there is no title.

    Normally one. A subtitle that came off for searching gives a second form to
    try in the same request, because the source may have kept it on its record.
    Both are the source's to answer, so both go in one query rather than two.
    """
    cleaned = clean_title(title)
    if not cleaned.search:
        return None
    return (cleaned.search, cleaned.also) if cleaned.also else (cleaned.search,)


def search_title(title):
    """The one title a source is asked about first, or None if the file has none."""
    titles = search_titles(title)
    return titles[0] if titles else None


def primary_language(language):
    """A file's language as the one code a source indexes it by.

    A `dc:language` is often a regional tag (`en-GB`) or the three-letter form
    (`eng`), and a source indexes editions by ISO 639-1 (`en`) or 639-2
    (`eng`). Every row in Hardcover's `languages` table carries both codes, so
    a two-letter tag is asked about on `code2` and a three-letter one on
    `code3`, and the two compare as the same language. A tag that is neither is
    left as it was written, less its region.
    """
    return str(language or "").split("-", 1)[0].split("_", 1)[0].strip().casefold()


def score_candidate(file_book, candidate):
    """Score one candidate against the file it is being considered for.

    Title and author are scored separately and weighted; the series position
    the file's title carried, if any, then nudges the total. A candidate that
    agrees on neither title nor author, or on only one of the two, is not an
    explanation of this book, which is what `agrees` reports.
    """
    cleaned = clean_title(file_book.title)
    title_score, title_reason = _title_score(cleaned.search, candidate.title)
    author_score, author_reason = _author_score(file_book.authors, candidate.authors)
    # Rounded before the series nudge, so a title and an author that both agree
    # perfectly are exactly 1.0 rather than 1.0000000000000002 of it.
    weighed = round(TITLE_WEIGHT * title_score + AUTHOR_WEIGHT * author_score, 3)
    confidence = weighed + _series_adjustment(cleaned.series_number, candidate.series_number)
    if not (title_score > 0.0 and author_score > 0.0):
        # One half alone is not a match, however good the other half was. Held
        # under the threshold so that `agrees` is never the only thing standing
        # between a wrong book and someone's library.
        confidence = min(confidence, NO_AGREEMENT_CEILING)
    return Match(
        candidate=candidate,
        confidence=round(min(confidence, 1.0), 4),
        title_score=title_score,
        author_score=author_score,
        title_reason=title_reason,
        author_reason=author_reason,
    )


def best_candidate(file_book, candidates, threshold):
    """The candidate that best explains this file, or None if none does.

    The nearest candidate is measured against the threshold and comes back only
    if it clears it: being the best of a bad set is not a match, and there is
    no second place to fall back to.
    """
    match = nearest_candidate(file_book, candidates)
    if match is None or not match.agrees or match.confidence < threshold:
        return None
    return match


def nearest_candidate(file_book, candidates):
    """The candidate closest to this file, whether or not it is close enough.

    What a book that was passed over is named by. A candidate in another
    language is not this book at all, so it is left out however well it scores:
    non-English books are matched in their own language and nothing is
    translated. Ties go to the first candidate, which is the order the source
    offered them in.
    """
    nearest = None
    for candidate in candidates:
        if not _same_language(file_book.language, candidate.language):
            continue
        match = score_candidate(file_book, candidate)
        if nearest is None or match.confidence > nearest.confidence:
            nearest = match
    return nearest


def _series_adjustment(wanted, found):
    """What the file's series number says about a candidate's.

    Two positions that disagree are a doubt about the candidate, not a verdict:
    a file that says book 6 may have been matched to a record that says 11, and
    when the title and the author both agree exactly it still is that book.
    Either side saying nothing is no evidence either way, which is the usual
    case - most files carry no series bracket at all, and a source need not have
    a position for a book.
    """
    if not wanted or not found:
        return SERIES_UNKNOWN
    return SERIES_CONFIRMED if str(wanted) == str(found) else SERIES_DISAGREEMENT


def normalise(text):
    """Text stripped of everything that is spelling rather than substance.

    Case, punctuation and symbols all go, so `L. J. Ross`, `L.J. Ross` and
    `lj ross` are one name. This is for comparison only: the values written
    into a file are the source's own, symbols and accents and all.
    """
    return " ".join(_WORDS.findall(str(text or "").casefold()))


def _title_score(cleaned, title):
    """How well a candidate's title explains the file's cleaned title."""
    wanted = normalise(cleaned)
    found = normalise(title)
    if not wanted or not found:
        return NO_TITLE, "no title on one side"
    if wanted == found:
        return EXACT_TITLE, "same title"
    # One title is the other with words around it, e.g. a source keeping the
    # subtitle on the record. Whole words only, so "Crag" is not "Cragside".
    if f" {wanted} " in f" {found} ":
        return CONTAINED_TITLE, "file's title is contained in the record's"
    if f" {found} " in f" {wanted} ":
        return CONTAINED_TITLE, "record's title is contained in the file's"
    return NO_TITLE, "different titles"


def _author_score(file_authors, record_authors):
    """Whether any creator the file names is any author the record names.

    Compared as sorted words with the spacing taken out, so the punctuation and
    the word order both stop mattering: `L. J. Ross`, `L.J. Ross` and the
    surname-first `Ross, L. J.` are one name.
    """
    wanted = {_name(author) for author in file_authors} - {""}
    found = {_name(author) for author in record_authors} - {""}
    if not wanted:
        return NO_AUTHOR, "the file names no author"
    if not found:
        return NO_AUTHOR, "the record names no author"
    if wanted & found:
        return MATCHING_AUTHOR, "an author agrees"
    return NO_AUTHOR, "no author agrees"


def _name(author):
    """A name as its characters run together, whichever way round it is spelt.

    A `Surname, Given` name is turned round at the first comma, so it starts
    the same way as the `Given Surname` a source usually writes. After that the
    word characters are joined up as they came, which is what makes the stops
    and the spacing stop mattering: `L.J. Ross`, `L. J. Ross`, `LJ Ross` and
    `Ross, L. J.` all come out as `ljross`.
    """
    text = str(author or "").casefold()
    surname, comma, given = text.partition(",")
    if comma:
        text = f"{given} {surname}"
    return "".join(_WORDS.findall(text))


def _split_subtitle(raw):
    """A title with its subtitle taken off it, when the subtitle names nothing.

    `Cragside: A DCI Ryan Mystery` is one book; `The Lord of the Rings: The
    Fellowship of the Ring` is two, so only a subtitle that says what kind of
    book this is comes off.
    """
    parts = _SUBTITLE.split(raw, maxsplit=1)
    if len(parts) < 2:
        return raw
    head, subtitle = _squeeze(parts[0]), _squeeze(parts[1])
    if not head or not _generic(subtitle):
        return raw
    return head


def _generic(subtitle):
    """Whether a subtitle says what kind of book this is, rather than which one."""
    return bool(_GENERIC_SUBTITLE.search(subtitle)) or subtitle.lower().startswith(("a ", "an "))


def _same_language(wanted, found):
    """Whether a candidate's language is the file's, either of them maybe unknown.

    Nothing is translated: a candidate in another language is not this book.
    Both sides are reduced to their primary subtag first, so a file that says
    `en-GB` agrees with an edition that says `en`. A file that says `eng` and an
    edition that says `eng` agree; `eng` against `en` does not, because the
    client reads what the source writes (`code2` when there is one, and that is
    what a client asks about). A missing language on either side is no evidence
    either way.
    """
    if not wanted or not found:
        return True
    return primary_language(wanted) == primary_language(found)


def _squeeze(text):
    """Collapse runs of whitespace, which titles of any age are full of."""
    return re.sub(r"\s+", " ", str(text or "")).strip()
