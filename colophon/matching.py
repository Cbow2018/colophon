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
    """A file's title, as much as a source needs to be asked about it."""

    raw: str
    search: str
    subtitle: str | None = None
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
    """One book a source offered, as the source describes it."""

    title: str | None
    authors: tuple = ()
    series: str | None = None
    series_number: str | None = None
    language: str | None = None
    isbn: str | None = None


@dataclass(frozen=True)
class Match:
    """How a candidate compares with the file, and whether it may be applied.

    `confidence` is the number the pipeline applies its 0.85 threshold to, and
    `agrees` is whether the comparison found anything to go on at all: the
    titles have something in common and so do the authors. A candidate that
    does not `agree` must not be accepted whatever the number says - and the
    weights mean it would not clear the threshold anyway.
    """

    confidence: float
    title_score: float
    author_score: float
    agrees: bool
    title_reason: str
    author_reason: str


def clean_title(title):
    """Take the series bracket and the subtitle off a title, keeping both.

    The series name and number in the bracket are captured rather than thrown
    away, and the subtitle is kept alongside the cleaned title, so a caller can
    put the whole title back together. The cleaned title is what gets asked
    about: `books.title` holds the clean work title, so a title with the
    subtitle or the bracket still on it matches nothing at all.
    """
    raw = _squeeze(str(title or ""))
    if not raw:
        return CleanedTitle(raw="", search="")

    series = None
    series_number = None
    bracket = _SERIES_BRACKET.search(raw)
    if bracket:
        series = _squeeze(bracket.group("series")) or None
        series_number = f"{float(bracket.group('number')):g}"
        raw = _squeeze(raw[: bracket.start()] + " " + raw[bracket.end() :])

    head, subtitle = _split_subtitle(raw)
    return CleanedTitle(
        raw=raw, search=head, subtitle=subtitle, series=series, series_number=series_number
    )


def title_variants(title):
    """The titles worth asking a source about, best first.

    One, always: the cleaned title. The subtitle and the series bracket are the
    two things the sources do not spell the same way as the file, and both are
    gone by the time this runs. It returns a list because the query asks about
    several titles at once, so a later ticket can add forms without changing
    the caller.
    """
    cleaned = clean_title(title)
    return [cleaned.search] if cleaned.search else []


def compared(file_book, candidate):
    """Score one candidate against the file it is being considered for.

    Title and author are scored separately and weighted. A candidate that
    agrees on neither, or on only one of the two, cannot reach the threshold;
    `agrees` says whether there was anything to go on at all.
    """
    cleaned = clean_title(file_book.title)
    title_score, title_reason = _title_score(cleaned.search, candidate.title)
    author_score, author_reason = _author_score(file_book.authors, candidate.authors)
    return Match(
        confidence=round(TITLE_WEIGHT * title_score + AUTHOR_WEIGHT * author_score, 4),
        title_score=title_score,
        author_score=author_score,
        agrees=title_score > 0.0 and author_score > 0.0,
        title_reason=title_reason,
        author_reason=author_reason,
    )


def best_candidate(file_book, candidates):
    """The candidate that best explains this file, or None if none does.

    A candidate in another language is not this book at all, so it is left out
    however well it scores: non-English books are matched in their own language
    and nothing is translated. Ties go to the first candidate, which is the
    order the source offered them in; a later one has to be strictly better.
    """
    best = None
    for candidate in candidates:
        if not _same_language(file_book.language, candidate.language):
            continue
        match = compared(file_book, candidate)
        if not match.agrees:
            continue
        if best is None or match.confidence > best[1].confidence:
            best = (candidate, match)
    return best


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
    """Whether any creator the file names is any author the record names."""
    wanted = {_name(author) for author in file_authors} - {""}
    found = {_name(author) for author in record_authors} - {""}
    if not wanted:
        return NO_AUTHOR, "the file names no author"
    if not found:
        return NO_AUTHOR, "the record names no author"
    if wanted & found:
        return MATCHING_AUTHOR, "an author agrees"
    # A record that spells the name the other way round - `Ross, LJ` - is the
    # same name, so both sides are compared in both orders.
    if {_reversed(name) for name in wanted} & found:
        return MATCHING_AUTHOR, "an author agrees, surname first on one side"
    return NO_AUTHOR, "no author agrees"


def _name(author):
    """A name reduced to its words, so `L. J. Ross` becomes `lj ross`."""
    return "".join(_WORDS.findall(str(author or "").casefold()))


def _reversed(name):
    """A run-together name with its words the other way round, for `Ross, LJ`."""
    return "".join(_WORDS.findall(str(name or "").casefold())[::-1])


def _split_subtitle(raw):
    """A title split at its subtitle, when the subtitle is decoration only."""
    parts = _SUBTITLE.split(raw, maxsplit=1)
    if len(parts) < 2:
        return raw, None
    head, subtitle = _squeeze(parts[0]), _squeeze(parts[1])
    if not head or not _generic(subtitle):
        return raw, None
    return head, subtitle


def _generic(subtitle):
    """Whether a subtitle says what kind of book this is, rather than which one."""
    return bool(_GENERIC_SUBTITLE.search(subtitle)) or subtitle.lower().startswith(("a ", "an "))


def _same_language(wanted, found):
    """Whether a candidate's language is the file's, either of them maybe unknown.

    Nothing is translated: a candidate in another language is not this book.
    A missing language on either side is no evidence either way.
    """
    if not wanted or not found:
        return True
    return str(wanted).strip().casefold() == str(found).strip().casefold()


def _squeeze(text):
    """Collapse runs of whitespace, which titles of any age are full of."""
    return re.sub(r"\s+", " ", str(text or "")).strip()
