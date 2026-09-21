"""Cleaning a file's title, and grading a candidate against the file.

A book with no ISBN is matched on its title and its author. Both sides of that
comparison are messy in their own way, so this module does the whole
comparison: it cleans the file's title down to what a source would call the
book, normalises both sides' spelling for comparison, and grades each candidate
with a weighted penalty accumulator, over a pool, into one of four bands.

Nothing here changes a value that gets written. Every normalisation is for
comparison only, and the written values stay exactly as the source spells them.

Every function here is pure: a pool of candidates in, a result out. Nothing
reads config, touches a file or reaches the network - which is what makes the
whole matcher unit-testable without a source, and is why the band decision
lives here while the *acting* on a band belongs to the pipeline.

The pipeline compares with `comparison_text`, which strips accents and articles
and is deliberately aggressive. `normalise` is a different function on purpose:
it is the record's durable key, it is frozen, and the golden test in
`tests/test_matching.py` is what keeps it that way. See `normalise` below.
"""

import difflib
import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise

# How much each field's disagreement counts towards the verdict. They are
# relative: only their ratios reach the score, so scaling them all changes
# nothing and adding one changes every book's score a little. ISBN is not
# scored at all - a stale or print-edition ISBN is common, and a field whose
# whole contribution would be deciding near-ties decides them with the noisiest
# evidence in the set. Publisher is dropped for the same reason, which is why
# `FileBook` does not carry one.
TITLE_WEIGHT = 1.00
AUTHOR_WEIGHT = 0.80
SERIES_WEIGHT = 0.20
YEAR_WEIGHT = 0.15

# The most a candidate can score while its author does not agree. Kept at the
# value the shipped rule used, so the number in a log line stays comparable.
NO_AGREEMENT_CEILING = 0.7

# The smallest author similarity that counts as agreement. A policy choice
# rather than a measurement: `L. J. Ross`/`L. J. Riss` (a typo) and
# `L. J. Ross`/`L. K. Ross` (a different person) both score 0.6814, so no value
# of this floor separates them. It errs towards admitting a wrong author who
# shares initials and a surname rather than refusing a real variant.
AUTHOR_AGREES = 0.5

# The calibrated similarity: `1 - penalty`. Above the dead band two strings are
# close enough that nothing meaningful separates them, so the penalty is a
# clean zero and a perfect match is exactly 1.0 rather than 0.997. Below the
# floor a wholly different title is a clean 1 rather than 0.65. Between them
# the penalty interpolates along straight lines, which is deliberately harsher
# than the raw ratio: `difflib` is over-generous on short strings.
SIMILARITY_KNOTS = (
    (0.35, 1.00),
    (0.50, 0.88),
    (0.60, 0.78),
    (0.70, 0.63),
    (0.80, 0.45),
    (0.90, 0.22),
    (1.00, 0.00),
)
SIMILARITY_DEAD_BAND = 0.97
SIMILARITY_FLOOR = 0.35

# The bands. A pool of one has no runner-up to corroborate its leader, so it
# has to clear a higher bar; a pool of two or more has to clear the lower one
# *and* be separated from its runner-up by `BAND_GAP`.
SINGLETON_STRONG = 0.95
STRONG_SCORE = 0.89
MEDIUM_SCORE = 0.80
BAND_GAP = 0.08

# `SequenceMatcher` is quadratic in input length, so every comparison caps its
# inputs. Descriptions are thousands of characters and are never compared.
MAX_TITLE_CHARS = 200
MAX_NAME_CHARS = 100

# How many candidates one source may offer for a prompt.
CANDIDATES_PER_SOURCE = 5

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
_WORD = re.compile(r"(\w+)", re.UNICODE)
# One letter, as opposed to one character: a digit on its own is not an initial.
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
# A full stop that sits between two letters, or after one at the end of a word,
# is part of an initial. One after a digit is a decimal point, and one after a
# closing bracket or quote ends a sentence; neither is touched.
_INITIAL_DOT = re.compile(r"(?<=[^\W\d_])\.(?=[^\W\d_])")
_TRAILING_DOT = re.compile(r"(?<=\b[^\W\d_])\.(?=\s|$)")
_ARTICLES = ("the ", "a ", "an ")
# The year a record's date starts with, when it has one.
_YEAR = re.compile(r"^(\d{4})")
# The two language-code forms a source may state an edition in.
_LANGUAGE_FORMS = (2, 3)


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
    """What the file says about itself, for the comparison's half of the work.

    `date` is the file's own `dc:date`, and the only field it carries that the
    score uses. Publisher is not here: it is not scored, so it would be a field
    nothing reads.
    """

    title: str
    authors: tuple = ()
    language: str | None = None
    date: str | None = None


@dataclass(frozen=True)
class Candidate:
    """One book a source offered, as the source describes it.

    `source` names where it came from, so a candidate can be written into a
    file without anything else having to remember who offered it. Every field a
    rule can write is here and defaults to None, which is how a source spells
    "I have nothing for this one" - a source with no publisher has not offered a
    blank one, and the two must not be written the same way.

    `title` is the title as the source writes it, subtitle included when the
    source has one, whether it keeps that in a field of its own or folded into
    one string.

    `author_ids` and `series_id` are the source's own identities for the names
    above them, in the same order, and they are **not values to write**: they
    exist so the record can recognise a name it has already settled on when the
    same source spells it differently. A source with no ids leaves them empty,
    which is every Google Books match.
    """

    title: str | None
    authors: tuple = ()
    series: str | None = None
    series_number: str | None = None
    language: str | None = None
    isbn: str | None = None
    source: str | None = None
    description: str | None = None
    publisher: str | None = None
    date: str | None = None
    cover: str | None = None
    author_ids: tuple = ()
    series_id: int | str | None = None
    # The genres the source tagged this book with, as `(genre, the source's own
    # string it came from)` pairs, in the source's order. They are what the
    # source said rather than values to write: genres are mapped onto the user's
    # own list before any reach a file, and nothing about that mapping belongs
    # here.
    genres: tuple = ()


@dataclass(frozen=True)
class Match:
    """One candidate measured against the file, and what came of the measuring.

    `score` is `1 - Σ(weight × penalty) / Σweights`, over the fields both sides
    supply and, when the author gate fails, without the author. It is 1.0 when
    nothing the file states contradicts the record and 0.0 when nothing agrees.

    `denominator` is the total weight that was actually compared, so a caller
    can see how much of the file the number was made from. `author_agrees` is
    §1.3's gate: the file names a creator, the record names one and the best
    file creator reaches `AUTHOR_AGREES` against some record author. When it is
    false the author's weight has already left the denominator and the score is
    held under `NO_AGREEMENT_CEILING`, so a candidate that is not an
    explanation of this file cannot be written from whatever the rest says.
    """

    candidate: Candidate
    score: float
    denominator: float
    title_similarity: float
    author_similarity: float | None
    author_agrees: bool
    title_reason: str
    author_reason: str

    @property
    def agrees(self):
        """Whether the comparison found anything to go on at all.

        The author gate plus a title with something in common: a candidate that
        agrees on the author and on *no* title is not an explanation of this
        book, and the caller that names a near miss reads this rather than the
        number. The cap and `author_agrees` are the gate alone, because §1.3
        takes the author's weight out of the denominator on the gate and nothing
        else; this is the stricter verdict a log line wants.
        """
        return self.author_agrees and self.title_similarity > 0.0

    @property
    def why(self):
        """What was wrong with this candidate, for a log line about a near miss."""
        return f"{self.title_reason}; {self.author_reason}"


@dataclass(frozen=True)
class Ranked:
    """One file's pool, ordered, with the band it grades and what led to it.

    `matches` is every candidate that survived the language filter, best first
    with ties left in the order the source offered them. Everything else is
    derived from that ordering, so nothing can disagree with it: `leader` is the
    best match, `runner_up` the second, `gap` how far apart they are, and `band`
    is `band_of`'s answer. `runner_up` and `gap` are None for a pool of one,
    which is the common case and the reason a singleton is graded against a
    higher bar.
    """

    matches: tuple = ()

    @property
    def leader(self):
        """The best match, or None when the pool is empty."""
        return self.matches[0] if self.matches else None

    @property
    def runner_up(self):
        """The second best match, or None when there is only one."""
        return self.matches[1] if len(self.matches) > 1 else None

    @property
    def gap(self):
        """How far the leader is clear of the runner-up, or None without one."""
        if self.runner_up is None:
            return None
        return round(self.leader.score - self.runner_up.score, 4)

    @property
    def band(self):
        return band_of(self)


def clean_title(title):
    """Take the series bracket and the subtitle off a title.

    The series number in the bracket is captured rather than thrown away,
    because it is the one fact about the book the title carries that a source
    keeps elsewhere. The cleaned title is what gets asked about: `books.title`
    holds the clean work title, so a title with the subtitle or the bracket
    still on it matches nothing at all. What the subtitle was taken off *from*
    is kept as `also`, because a source is free to have kept it.

    This decides what gets *asked about*, never what gets scored: the scored
    form is the source's own title (§3.3).
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

    This is not the language guarantee: the query carries that, and the matcher
    only drops what it can prove. See `_same_language` below.
    """
    return str(language or "").split("-", 1)[0].split("_", 1)[0].strip().casefold()


def comparison_text(text):
    """Text reduced to what a comparison should still be able to see, capped.

    Decomposed, stripped of the combining marks, case-folded, `&` read as
    `and`, every other non-alphanumeric turned into a space, and a leading
    article dropped. So `Brontë` is `bronte`, `The Wind & the Willows` is
    `wind and the willows`, and `The Waste Land.` is `waste land`.

    The article goes only when at least two tokens are left, so `The Infirmary`
    keeps its article and a book merely called *A* keeps its title. The rule is
    the title's: an author named `A. Smith` is not an article.

    The result is capped at `MAX_TITLE_CHARS`, because `difflib` is quadratic in
    input length and a comparison key has no business being longer.

    Not a transliterator. NFKD plus stripping the marks covers accented Latin
    text with no table and no dependency; a Cyrillic or CJK title is left as it
    is, and is compared against records in the same script where exact equality
    does the job. That is deliberate, so please do not add `unidecode` for it.
    """
    key = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(text or ""))
        if not unicodedata.combining(char)
    )
    spaced = "".join(
        char if char.isalnum() else " " for char in key.casefold().replace("&", " and ")
    )
    squeezed = re.sub(r"\s+", " ", spaced).strip()[:MAX_TITLE_CHARS].strip()
    return _drop_article(squeezed)


def normalise(text):
    """Text stripped of everything that is spelling rather than substance.

    Case, punctuation and symbols all go, so `L. J. Ross`, `L.J. Ross` and
    `LJ Ross` are one name. A run of initials is then joined into one token,
    because initials are what a library spells inconsistently and the whole
    point is that `J.R.R. Tolkien` and `JRR Tolkien` come out the same. Written
    words never join, so `Ursula K. Le Guin` keeps its words and never becomes
    `ursulakleguin`: a one-letter word only ever joins a run that is already
    initials, never the word beside it. Digits are left alone for the same
    reason — a version string is not initials, and `1.0.0` is `1 0 0`, not
    `10 0`.

    **FROZEN, and not the comparison pipeline.** CBO-41 keys the record's name
    standard by this, and that key is written into a library and kept, so
    changing it would silently re-key every stored name and write a second
    spelling of every author. The comparison uses `comparison_text`, which
    strips accents and articles and is free to change. The golden test in
    `tests/test_matching.py` pins this one's output so it can only move on
    purpose.
    """
    return " ".join(_join_initials(_words(text)))


def score_candidate(file_book, candidate):
    """Score one candidate against the file it is being considered for.

    Each field both sides supply contributes `weight × penalty` to a sum that is
    divided by the weight actually compared, so the result is on a 0–1 scale
    whichever fields were available: a file with a title and a year and a file
    with everything are both 1.0 when nothing contradicts them. The score is
    that fraction inverted, which is what makes a penalty model rather than a
    reward model: the only way to score highly is to have nothing wrong.

    The author is the exception. When the gate at `AUTHOR_AGREES` fails - the
    file names no creator, the record names none, or the best file creator does
    not reach the floor against any record author - the author's weight leaves
    the denominator rather than diluting the score towards zero, and the result
    is capped at `NO_AGREEMENT_CEILING`. A title alone is not a match, and that
    has to hold arithmetically at every threshold a user can set.

    Every function here is pure, so this is too: it reads nothing but its two
    arguments.
    """
    head, subtitle, file_series_number = _parts_of(file_book.title)
    record_head, record_subtitle, _ = _parts_of(candidate.title)
    title_penalty, title_reason = _title_penalty(
        head, subtitle, record_head, record_subtitle
    )

    author_similarity, author_reason = _author_similarity(
        file_book.authors, candidate.authors
    )
    author_agrees = author_similarity is not None and author_similarity >= AUTHOR_AGREES

    counted = [(TITLE_WEIGHT, title_penalty)]
    if author_agrees:
        counted.append((AUTHOR_WEIGHT, 1.0 - author_similarity))
    if file_series_number and candidate.series_number:
        agrees = str(file_series_number) == str(candidate.series_number)
        counted.append((SERIES_WEIGHT, 0.0 if agrees else 1.0))
    file_year, record_year = _year(file_book.date), _year(candidate.date)
    if file_year and record_year:
        counted.append((YEAR_WEIGHT, 0.0 if file_year == record_year else 1.0))

    denominator = sum(weight for weight, _ in counted)
    weighted = sum(weight * penalty for weight, penalty in counted)
    score = 1.0 - (weighted / denominator) if denominator else 0.0
    if not author_agrees:
        score = min(score, NO_AGREEMENT_CEILING)

    return Match(
        candidate=candidate,
        score=round(min(score, 1.0), 4),
        denominator=round(denominator, 2),
        title_similarity=round(1.0 - title_penalty, 4),
        author_similarity=(
            None if author_similarity is None else round(author_similarity, 4)
        ),
        author_agrees=author_agrees,
        title_reason=title_reason,
        author_reason=author_reason,
    )


def rank(file_book, candidates):
    """Every candidate measured against the file, best first, and its band.

    The language filter is applied here: a candidate is dropped when the file
    states a language, the candidate states one, both are given in the same
    *form* - two letters or three - and the codes differ. A two-letter code
    against a three-letter one is kept and unflagged, because the matcher
    cannot decide it and a wrong drop costs a book. The guarantee that another
    language's edition is not offered at all is the source query's.

    Ties keep the order the source offered them in, which is a stable sort and
    the same rule the score has always used.
    """
    scored = [
        score_candidate(file_book, candidate)
        for candidate in candidates
        if _same_language(file_book.language, candidate.language)
    ]
    scored.sort(key=lambda match: match.score, reverse=True)
    return Ranked(matches=tuple(scored))


def dedupe(candidates):
    """One candidate per record, when a source offered the same book twice.

    A run of candidates is grouped by what identifies the record: its ISBN-13
    when it has one, and otherwise its normalised title, its first author and
    its year. The first of a group is the one kept, which is input order and
    therefore the source order the user configured.

    This is deliberately *not* `record.py`'s `book_key`, even though both are
    "title plus author": that one is a durable key for a library and this one is
    a comparison key for one reply. Merging the two would tie the matcher's
    grouping to the record's schema.
    """
    kept = []
    seen = set()
    for candidate in candidates:
        key = _identity(candidate)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        kept.append(candidate)
    return tuple(kept)


def band_of(ranked):
    """Which band a ranked pool falls in, and nothing else.

    One candidate has no runner-up to corroborate its leader, so it has to
    clear `SINGLETON_STRONG` rather than `STRONG_SCORE`. Two or more need the
    lower score *and* `BAND_GAP` of separation: a high score with a small gap
    says the metric is saturated rather than that the leader is right.

    `strong` needs the author to agree, so a candidate the gate refused - which
    is capped at `NO_AGREEMENT_CEILING` - can reach neither strong threshold.
    """
    leader = ranked.leader
    if leader is None:
        return "none"
    strong = (
        leader.score >= SINGLETON_STRONG
        if ranked.runner_up is None
        else leader.score >= STRONG_SCORE and (ranked.gap or 0.0) >= BAND_GAP
    )
    if strong and leader.author_agrees:
        return "strong"
    if leader.author_agrees and leader.score >= MEDIUM_SCORE:
        return "medium"
    return "low" if leader.score > 0.0 else "none"


def top_candidates(file_book, candidates):
    """The candidates worth putting to the LLM, best first.

    One source's reply at a time, and at most `CANDIDATES_PER_SOURCE` of them,
    because a source can return a long tail of lookalikes and every one of them
    costs tokens and buries the right record a little deeper. The cap is on the
    *best* few rather than the first few: the ones the source listed first are
    in whatever order its own search ranked them, while the score is what this
    project's rules make of them against this file. The best candidate is
    therefore candidate 1 in the prompt, which is the number a reply is read
    against.

    The cap is per source, so this is called once per source's own reply and not
    over everything the sources offered between them: otherwise the first source
    to answer would spend the whole prompt and a second source's best record
    would never be shown.

    Being ranked here does not mean being accepted: a candidate that agrees on
    neither title nor author is not an explanation of the book to the rules, and
    is still offered to the model - they read the title and the author, and the
    reason a book needs an LLM is usually that those two are not enough.
    """
    return [
        match.candidate
        for match in rank(file_book, candidates).matches[:CANDIDATES_PER_SOURCE]
    ]


def _title_penalty(file_head, file_subtitle, record_head, record_subtitle):
    """How much a candidate's title disagrees with the file's, and why.

    One form per side, chosen by whether *both* sides carry a subtitle. When
    both do, the full titles are compared, because the subtitle is where the
    discriminating words are. When one is bare, only the heads are compared:
    one identifier and one longer identifier are not two conflicting
    identifiers, and a record that keeps a subtitle the file dropped costs
    nothing.

    There is deliberately no max over forms. Comparing every form and taking the
    best makes any two titles that strip to the same head match at 1.0, which
    reads a different book's subtitle as an exact title match.
    """
    if file_subtitle is not None and record_subtitle is not None:
        rule = "the full titles"
        left = comparison_text(f"{file_head}: {file_subtitle}")
        right = comparison_text(f"{record_head}: {record_subtitle}")
    else:
        rule = "the heads"
        left, right = comparison_text(file_head), comparison_text(record_head)
    if not left or not right:
        return 1.0, "no title on one side"
    penalty = _penalty(_ratio(left, right))
    if penalty == 0.0:
        return 0.0, f"{rule} agree"
    return penalty, f"{rule} differ"


def _parts_of(title):
    """A raw title as `(head, subtitle, series position)`, before normalisation.

    The series bracket comes off first, because it is not part of the title and
    it is the one fact about the book the title carries that a source keeps
    elsewhere. The head/subtitle split then happens on the **raw** text:
    normalising first turns the colon into a space, and every title would
    silently be read as a head with no subtitle.
    """
    text = _squeeze(str(title or ""))
    series_number = None
    bracket = _SERIES_BRACKET.search(text)
    if bracket:
        series_number = f"{float(bracket.group('number')):g}"
        text = _squeeze(text[: bracket.start()] + " " + text[bracket.end() :])
    head, subtitle = _split_subtitle_parts(text)
    return head, subtitle, series_number


def _split_subtitle_parts(text):
    """A title split at its first colon, when both sides of the colon say something."""
    parts = _SUBTITLE.split(text, maxsplit=1)
    if len(parts) < 2:
        return text, None
    head, subtitle = _squeeze(parts[0]), _squeeze(parts[1])
    if not head or not subtitle:
        return text, None
    return head, subtitle


def _author_similarity(file_authors, record_authors):
    """How well the file's creators are covered by the record's, and why.

    Each creator the file names contributes the calibrated similarity of its
    **best** match against any author the record names, and those values are
    averaged. So a record that lists a second name the file omits - a
    co-author, a translator, an illustrator - costs the field nothing: the
    creator's best match is still the one that agrees.

    The two orderings this rules out both give a different answer. Averaging
    over every file creator against every record author is the cartesian mean,
    which divides a creator that matched by however many names the record
    happened to list; and averaging the raw ratios before calibrating them lets
    one very wrong creator be diluted by one very right one before the judgement
    is applied.

    Returns `(similarity, reason)`, with the similarity None when either side
    names nobody - silence is not agreement, and a file that names no author can
    never match on its title alone.
    """
    wanted = [key for key in (_name(author) for author in file_authors) if key]
    found = [key for key in (_name(author) for author in record_authors) if key]
    if not wanted:
        return None, "the file names no author"
    if not found:
        return None, "the record names no author"
    best = [max(_similarity(_ratio(key, other)) for other in found) for key in wanted]
    similarity = sum(best) / len(best)
    if similarity >= AUTHOR_AGREES:
        return similarity, "an author agrees"
    return similarity, "no author agrees"


def _name(author):
    """A name as the comparison key for it, reversed at the comma first.

    A `Surname, Given` name is turned round at the first comma, because a file
    and a source disagreeing about which way round a name goes is a formatting
    difference and must not be scored as a difference in substance.

    Everything the existing normalisation already collapses - the stops, the
    spacing, a run of initials - is collapsed **before** the similarity is
    asked, so the similarity only judges differences the normalisation could not
    remove. That ordering is the whole reason a surname typo scores 0.8308
    rather than 0.0000: `L. J. Ross` and `L. J. Ros` are `lj ross` and `lj ros`
    by the time `difflib` sees them, and *not* one run of characters, which
    would compare a six-character key against a five-character one and lose the
    surname's shape.

    The key is a word per token rather than one run of letters, which is what
    `normalise` already produces and what every number in the design's name
    table was measured with. The two differ only in what they throw away -
    `normalise` keeps accents and articles, this drops them - and in that this
    one reverses at the comma first.
    """
    text = str(author or "").strip()
    if not text:
        return ""
    surname, comma, given = text.partition(",")
    if comma:
        text = f"{given} {surname}"
    return " ".join(_join_initials(comparison_text(text)[:MAX_NAME_CHARS].split()))


def _ratio(left, right):
    """The raw `difflib` ratio between two comparison keys.

    A character ratio on the key as a whitespace-joined string, which is the
    reading the calibration exists to absorb. Comparing token lists instead
    would score every wrong author at 0.0000, because two names share no whole
    token - which is exactly the case the graded similarity is here for.

    Both keys are already capped at `MAX_TITLE_CHARS` by `comparison_text`.
    """
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _penalty(raw):
    """The penalty a raw ratio earns: dead band, floor, straight lines between."""
    if raw >= SIMILARITY_DEAD_BAND:
        return 0.0
    if raw < SIMILARITY_FLOOR:
        return 1.0
    for (low_raw, low), (high_raw, high) in pairwise(SIMILARITY_KNOTS):
        if low_raw <= raw <= high_raw:
            return low + ((raw - low_raw) / (high_raw - low_raw)) * (high - low)
    return 1.0


def _similarity(raw):
    """The calibrated similarity: 1 when nothing meaningful separates them."""
    return 1.0 - _penalty(raw)


def _same_language(file_language, candidate_language):
    """Whether a candidate is in the file's language, as far as can be proven.

    Dropped only when both sides state a code, both are given in the same form
    and the codes differ. "The same form" is both two letters or both three, and
    anything else is kept: a two-letter code against a three-letter one is the
    639-1/639-2 equivalence the query carries, and a tag that is neither is
    something this cannot read. A wrong drop costs a book.
    """
    wanted = primary_language(file_language)
    found = primary_language(candidate_language)
    if wanted == found or not _is_code(wanted) or not _is_code(found):
        return True
    return len(wanted) != len(found)


def _is_code(code):
    """Whether a language tag is the two-letter form or the three-letter one."""
    return len(code) in _LANGUAGE_FORMS and code.isalpha() and code.isascii()


def _identity(candidate):
    """What identifies a record for `dedupe`, or None when nothing does."""
    isbn = _isbn13(candidate.isbn)
    if isbn:
        return ("isbn", isbn)
    title = comparison_text(candidate.title)
    author = _name(candidate.authors[0]) if candidate.authors else ""
    year = _year(candidate.date)
    if not title or not author:
        return None
    return ("key", title, author, year)


def _isbn13(isbn):
    """The digits of an ISBN-13, or None when it is not one."""
    digits = "".join(char for char in str(isbn or "") if char.isdigit())
    return digits if len(digits) == 13 else None


def _year(date):
    """The four-digit year a date starts with, or None."""
    found = _YEAR.match(str(date or ""))
    return found.group(1) if found else None


def _drop_article(text):
    """The text without a leading article, when at least two tokens are left."""
    for article in _ARTICLES:
        if text.startswith(article) and len(text[len(article) :].split()) >= 2:
            return text[len(article) :].strip()
    return text


def _join_initials(words):
    """The words, with each run of initials joined into one token.

    A one-letter word joins the token before it **only when that token is itself
    a one-letter run**; otherwise it starts a run of its own. That single
    condition is the whole rule, and it is what tells `L. J. Ross` from `Ursula
    K. Le Guin`: `j` joins the `l` beside it and makes a run, while the `k` in
    `K. Le` has the word `ursula` before it and so never becomes one, which is
    why `le` and `guin` keep their own letters. The same condition is what stops
    `I am` becoming `Iam` — the `i` has nothing before it, and `am` is not a
    one-letter run to join.

    What a run may take next is fixed when it is born rather than recomputed: a
    token carries whether it is a run, so a word that merely happens to be one
    letter long by this point — `k` in `K. Le Guin` — cannot be mistaken for one
    and swallow the word after it.
    """
    joined = []
    for word in words:
        single = _LETTER.fullmatch(word) is not None
        if single and joined and joined[-1][1]:
            joined[-1][0] += word
        else:
            joined.append([word, single])
    return [word for word, _ in joined]


def _words(text):
    """The words in the text, with the full stops that make initials taken out.

    A full stop between two letters is part of an initial rather than a break, so
    `J.R.R.` is one word; one after a digit is a decimal point and one at the end
    of a sentence is an ending, and neither is touched. Every other kind of
    punctuation is a break, and `_WORD.split` keeps the separators between the
    groups it splits on, so the words are the odd-numbered parts. The text is
    casefolded here, so every reader of these words compares the same thing.
    """
    cleaned = _INITIAL_DOT.sub("", _TRAILING_DOT.sub("", str(text or "").casefold()))
    return _WORD.split(cleaned)[1::2]


def _split_subtitle(raw):
    """A title with its subtitle taken off it, when the subtitle names nothing.

    `Cragside: A DCI Ryan Mystery` is one book; `The Lord of the Rings: The
    Fellowship of the Ring` is two, so only a subtitle that says what kind of
    book this is comes off.
    """
    head, subtitle = _split_subtitle_parts(raw)
    if subtitle is None or not _generic(subtitle):
        return raw
    return head


def _generic(subtitle):
    """Whether a subtitle says what kind of book this is, rather than which one."""
    return bool(_GENERIC_SUBTITLE.search(subtitle)) or subtitle.lower().startswith(
        ("a ", "an ")
    )


def _squeeze(text):
    """Collapse runs of whitespace, which titles of any age are full of."""
    return re.sub(r"\s+", " ", str(text or "")).strip()
