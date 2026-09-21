"""The correction pass: read the book, ask a source, back it up, rewrite it.

The relay hands every incoming file to this. It decides whether the file is a
book worth correcting, reads the ISBN out of it, asks Hardcover, and writes
whatever the source is sure of. A book with no ISBN is asked about by its
cleaned title and author instead, and whatever comes back is only written if
the comparison is confident enough. It writes nothing when there is nothing to
change, nothing when there is no match, and nothing at all in dry-run mode -
and it backs the original up before it changes a byte, so a correction can
always be undone.
"""

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from colophon import epub
from colophon.config import (
    DEFAULT_MEDIUM_SCORE,
    DEFAULT_SINGLETON_SCORE,
    DEFAULT_STRONG_SCORE,
    FIELD_DEFAULTS,
    KNOWN_FIELDS,
)
from colophon.epub import UNVERIFIED_TAG, Edits, EpubError, unmarked
from colophon.googlebooks import GoogleBooks
from colophon.hardcover import Hardcover
from colophon.llm import (
    Llm,
    LlmError,
    LlmLimited,
    allowed_spelling,
    needs_key,
    utc_today,
)
from colophon.matching import (
    Bands,
    FileBook,
    Ranked,
    band_of,
    dedupe,
    primary_language,
    rank,
    search_titles,
    top_candidates,
)
from colophon.record import AUTHOR, SERIES, Match, book_key
from colophon.sources import SourceError, fetcher_for

LOG = logging.getLogger("colophon")

# One entry per source Colophon knows: the setting naming its key file, what to
# call the source in a sentence, what to call that key file, and how to build the
# source from it. A name missing from here is a programming mistake rather than a
# user one - `config.py` refuses a name it does not know long before this is
# reached - which is why the sentences live here too, rather than in a second map
# keyed by the same names.
SOURCE_SETUP = {
    "hardcover": {
        "file": "hardcover_token_file",
        "label": "Hardcover",
        "key_label": "Hardcover token",
        "make": Hardcover.from_secret_file,
    },
    "google_books": {
        "file": "google_books_key_file",
        "label": "Google Books",
        "key_label": "Google Books key",
        "make": GoogleBooks.from_secret_file,
    },
}

# An exact ISBN match is as certain as metadata matching gets.
CONFIDENCE = 1.0
MATCHED_BY = "exact ISBN"
TITLE_MATCHED_BY = "title and author"

# Who chose the record a book was corrected from, when it was not the rules.
LLM_CHOOSER = "llm"

# What a change is attributed to when Colophon itself made it rather than a
# source: the unverified tag, and the note in the description beside it. It is
# not a source name - no source can supply either - so it is spelled as the
# program that did it.
COLOPHON = "colophon"

# Fields whose values are not what belongs in a log line, so the line names them
# without it: the blurb is a thousand characters of prose that is in the book,
# and a cover's value is bytes. The line's job is which fields moved and who
# supplied them.
_NAME_ONLY = ("description", "cover", "tag")

# The formats whose metadata Colophon understands. Everything else - PDFs,
# comics, MOBI - passes straight through, untouched and unread. Kobo writes
# its own extension as well as the .kepub.epub one.
BOOK_SUFFIXES = (".epub", ".kepub")


@dataclass(frozen=True)
class Change:
    """One field that moved, and the source that supplied its new value."""

    field: str
    value: str
    source: str


@dataclass(frozen=True)
class Standards:
    """The spellings the record decided on for one book's names.

    Held apart from the corrections because they are not values a source
    offered: they are the library's own, and the book is written with them so
    that the same author is not spelt two ways across a shelf. `resolved` is
    what the record is told once the book has landed, and it is the only thing
    that ever becomes a new standard.
    """

    authors: tuple = ()
    series: str | None = None
    resolved: tuple = ()

    def applied_to(self, candidate):
        """This source's record, with the standard spellings in place of its own."""
        changes = {}
        if self.authors:
            changes["authors"] = self.authors
        if self.series is not None:
            changes["series"] = self.series
        return replace(candidate, **changes) if changes else candidate


@dataclass(frozen=True)
class Decision:
    """A match, and the names it settled on, for the relay to record.

    The corrector decides this, because it is the only thing that knows which
    names were resolved and under which keys; the relay persists it, because it
    is the only thing that knows the book was delivered. Passing it between them
    is what keeps a correction that never landed from teaching a standard.
    """

    resolutions: tuple = ()
    match: Match | None = None
    # What each of this book's source genres was judged to mean, as
    # `(source, genre, mapped, seen)`: the genre cache the record keeps, which
    # travels here for the same reason the resolutions do - the relay is what
    # knows the book arrived, and a mapping learnt from a book that never landed
    # is a mapping nothing on the shelf has.
    genres: tuple = ()


@dataclass(frozen=True)
class Outcome:
    """What became of one book, in enough detail for the relay's one log line."""

    isbn: str | None = None
    # The ISBN the file carried, whether or not it is what recognised the book.
    # Kept beside the one above because on the ISBN path the two can differ: no
    # source may have that ISBN, and the title path may then recognise the book
    # by its title - which is a match, but not an ISBN one, and the line must not
    # say the ISBN found what a title search found.
    carried_isbn: str | None = None
    # What the source was asked about, when that was not an ISBN: the cleaned
    # title a book without one was recognised by.
    sought: str | None = None
    matched: bool = False
    confidence: float | None = None
    source: str | None = None
    changed: tuple = ()
    applied: bool = False
    problem: str | None = None
    silent: bool = False
    # Where the original was kept before it was changed, if it was.
    kept: str | None = None
    # Why the best candidate was not good enough, when there was one and it
    # was not. Empty whenever a match was made or none was offered.
    passed_over: str | None = None
    # Which sources were asked, and did not have the book. Only filled in when
    # nothing matched, because that is the case where the reader of the log has
    # nothing else to go on about what was tried.
    tried: tuple = ()
    # Whether the book was marked `colophon:unverified`. A book nothing matched
    # confidently is not corrected - it keeps the metadata it came with - but it
    # is marked, so it can be found in the library without reading a log.
    unverified: bool = False
    # Whether a correction was actually written. A dry run reports every change
    # and applies none, so the two cannot be told apart from `changed`.
    dry_run: bool = False
    # Whether the book is waiting for the next UTC day, because the pass did not
    # finish with it: the LLM could not be asked - it is down, its key was
    # refused, or the day's calls are spent - or a source the user configured
    # could not be asked at all. The file is left exactly as it was, in the
    # ingest folder, and the relay must not deliver it.
    waiting: bool = False
    # Why it is waiting, for its own log line.
    note: str | None = None
    # What the LLM answered, when it was asked: the number it picked, its own
    # self-reported confidence, and its reason. All three are recorded rather
    # than acted on beyond the pick, because the number is the model's own and
    # not the same scale as `score_candidate`'s.
    llm_pick: int | None = None
    llm_confidence: float | None = None
    llm_reason: str | None = None
    # Which chose the record the book was corrected from: "llm" when the model
    # picked it, None when the rules did.
    chosen_by: str | None = None
    # What the record should be told once this book has landed, or None when
    # there is nothing to tell it. The relay is what knows the book arrived, so
    # the decision travels there rather than being written here.
    decision: Decision | None = None

    def fragment(self):
        """The bracketed part of the log line, or nothing when there is nothing to say."""
        if self.silent:
            return ""
        if self.waiting:
            return f"[left in the ingest folder: {self.note}; trying again tomorrow]"
        if not self.matched:
            if self.problem is not None:
                return f"[{self.problem}]"
            if self.passed_over is not None:
                # The best explanation of this file, and what was wrong with it.
                # The sources are named here for the same reason they are named
                # when nothing was found at all: the reader has no match to
                # anchor on, and "confidence 0.84 - against which source?" is
                # the next question they would have.
                return (
                    f"[no source{self._among()} has an edition called {self.sought} "
                    f"confidently enough: {self.passed_over}, "
                    f"confidence {self.confidence:.2f}{self._carried()}"
                    f"{self._llm_said()}{self._marking()}]"
                )
            return f"[{self._nothing_found()}{self._llm_said()}{self._marking()}]"

        if self.isbn:
            head = (
                f"{self.source} matched ISBN {self.isbn} by {MATCHED_BY}, "
                f"confidence {self.confidence:.2f}"
            )
        else:
            head = (
                f"{self.source} matched {self.sought} by {TITLE_MATCHED_BY}, "
                f"confidence {self.confidence:.2f}"
            )
        picked = (
            f" ({LLM_CHOOSER} picked candidate {self.llm_pick}, its own confidence "
            f"{self.llm_confidence:.2f}: {self.llm_reason})"
            if self.chosen_by == LLM_CHOOSER
            else ""
        )
        if self.problem is not None:
            return f"[{head}{picked}; nothing written: {self.problem}]"
        if not self.changed:
            return f"[{head}{picked}; nothing to change]"

        return (
            f"[{head}{picked}; {'changed' if self.applied else 'would change'} "
            f"{_names_and_values(self.changed)}]"
        )

    def _among(self):
        """The sources that were tried, for the log lines that have no match.

        A book that was matched says which source matched it, and the sources
        that were passed over on the way are reconstructible from the config. A
        book that was not matched has no such anchor, so the sources that were
        actually asked are worth writing down - on both the near-miss line and
        the nothing-found line, which are the two that have no match to name.
        """
        return f" among {', '.join(self.tried)}" if self.tried else ""

    def _llm_said(self):
        """What the LLM answered, when it answered and there is nothing to write.

        A null pick is an answer, and it can come with a confidence of 1.0 - the
        model is certain none of them is the book - so the line records the
        number without ever letting it read as a reason to write.
        """
        if self.chosen_by == LLM_CHOOSER or self.llm_confidence is None:
            return ""
        said = (
            "said none of them"
            if self.llm_pick is None
            else f"picked candidate {self.llm_pick}, which is not sure enough"
        )
        return (
            f"; the {LLM_CHOOSER} {said}, its own confidence "
            f"{self.llm_confidence:.2f}: {self.llm_reason}"
        )

    def _carried(self):
        """The ISBN the book came with, when the line is about something else.

        A book whose ISBN found nothing is looked up by its title as well, and the
        line is then about the title. The ISBN it came with is still the first
        thing anyone would check, so it is named beside it rather than dropped:
        otherwise the log says a book called *Cragside* was not found, and says
        nothing about the identifier that was wrong.
        """
        if self.carried_isbn and self.sought:
            return f", or by ISBN {self.carried_isbn}"
        return ""

    def _marking(self):
        """The note that a book nothing matched was marked, and by what.

        Said out loud because the line is otherwise only about what was not
        found, while the book itself has been changed - or would be, in a dry run,
        which is why the mark is the one thing here that says which: there is no
        `changed` list after the word "changed" for it to sit behind. The fields
        are named the way a matched book's are, and for a book nothing matched
        they are Colophon's own, which is worth showing as plainly as a source's
        name is.
        """
        if not self.unverified:
            return ""
        # "would" is the dry run's word, and it is asked of the mode rather than
        # of whether anything moved: a book that is already marked and still
        # unmatched has nothing to write but is still, on a real pass, marked -
        # and a line calling that a "would" would be wrong in the other direction.
        marked = f"; {'would mark' if self.dry_run else 'marked'} {UNVERIFIED_TAG}"
        return (
            f"{marked}: {_names_and_values(self.changed)}" if self.changed else marked
        )

    def _nothing_found(self):
        """The line for a book not one source had, naming every source asked."""
        if self.sought:
            return (
                f"no source{self._among()} has an edition called {self.sought}"
                f"{self._carried()}"
            )
        return f"no source{self._among()} carries ISBN {self.isbn}"


@dataclass(frozen=True)
class Walk:
    """What one book's title walk gathered, and how it stopped.

    `asked` is the sources that answered, in the order the user ranked them,
    which is also the sources whose candidates are in the pool. `errored` is
    `(source, reason)` for each source that could not be asked: a walk that
    errored is not a walk that finished, and a book graded against a pool
    missing a source the user configured is not a book the rules refused.
    `exited` says the walk stopped on purpose, because the pool as it then stood
    graded strong - a source that was never reached by a decision is not a
    source that failed.

    Half-asked is the two of those together, `errored and not exited`, which is
    §4.2's rule as one expression rather than a third state.

    `ranked` is the pool as it finally stood: deduped in priority order and
    measured once, so the band, the leader and the gap all come from one
    grading. An unanswered walk is an empty pool, which grades `none`.
    """

    asked: tuple = ()
    errored: tuple = ()
    exited: bool = False
    ranked: Ranked = field(default_factory=Ranked)


class Corrector:
    """Corrects the books the relay hands it, one file at a time.

    `sources` is the priority list, in the order the user set: both the ISBN
    path and the title path walk the same list. An empty list - no source
    configured, or none of them usable - means every book passes through with
    the metadata it came with.

    The title path pools the sources rather than racing them: every configured
    source is asked, every reply joins one pool, and the pool is deduped and
    graded as it then stands. `dedupe` keeps the first record of a group, so the
    pool is built source by source in the order the user ranked them and the
    record that survives a group is the one from the highest-priority source
    that offered it. A source that cannot answer does not end the walk either:
    it is recorded, the next source is asked, and a walk that finished with a
    source missing leaves the book held for tomorrow rather than written or
    marked - a pool missing a source the user configured is not a verdict on
    the book. What happens to a held book after that belongs to the retry window
    (CBO-43).

    `dry_run` decides whether a correction is actually written: in a dry run
    every answer is the same, except that nothing on disk moves, including the
    backup.
    """

    def __init__(
        self,
        sources=None,
        backups=None,
        dry_run=False,
        fields=None,
        add_cover=True,
        fetch=None,
        strong_score=DEFAULT_STRONG_SCORE,
        singleton_score=DEFAULT_SINGLETON_SCORE,
        medium_score=DEFAULT_MEDIUM_SCORE,
        llm_full_scan=True,
        llm=None,
        record=None,
        overrides=None,
        genres=(),
    ):
        self.sources = tuple(sources or ())
        self.backups = backups
        self.dry_run = dry_run
        # What to do with each field, as a mapping: `skip`, `fill` or
        # `overwrite`. A field the mapping leaves out is one nothing has an
        # opinion about, so it is simply not written.
        self.fields = dict(fields or FIELD_DEFAULTS)
        self.add_cover = add_cover
        # How sure a title-and-author match has to be before it counts as one:
        # `strong_score`, the multi-candidate bar. The bands the walk acts on are
        # built from this and the two thresholds below, and the LLM's own pick is
        # held to `strong_score` rather than to the singleton bar - a model
        # picking one of two near-identical candidates has answered the question
        # the gap could not: see docs/research/cbo-40-llm-fallback-chooser.md,
        # Q4.
        self.strong_score = strong_score
        # The three thresholds as one value, which is what `band_of` takes: the
        # matcher reads no config, so the policy has to arrive as an argument.
        self.bands = Bands(
            strong=strong_score, singleton=singleton_score, medium=medium_score
        )
        # Whether a book the rules could not decide goes to the LLM from any
        # non-strong band, or only from the medium one. It widens which uncertain
        # books reach the model; it does not disable early exit, and it does not
        # make a book the rules already graded strong spend a call. On by
        # default, because that is the reach the walk had before the bands
        # existed: `off` is the narrowing, and a user asks for it.
        self.llm_full_scan = llm_full_scan
        # The fallback chooser, or None when the user has not set one up. No LLM
        # means uncertain books take the unverified path rather than waiting.
        self.llm = llm
        # Colophon's own record of the spellings this library has settled on, or
        # None when there is none: a missing record means every book is written
        # with the source's own spelling, exactly as it was before this existed.
        self.record = record
        # The `[authors]` overrides, keyed by normalised name, which beat
        # whatever the record says.
        self.overrides = dict(overrides or {})
        # The user's own tag list. A source genre is mapped onto one of these or
        # dropped, so this is the only vocabulary that ever reaches a book, and
        # an empty list means genres are not written at all.
        self.allowed_genres = tuple(genres or ())
        # What each source genre was judged to mean, for this run only. The record
        # is the durable cache; this is what makes a run that never lands still
        # ask each genre once, rather than once per book carrying it.
        self._genre_memo = {}
        # Books the LLM could not be asked about, and why, for the UTC day they
        # were left for: a cache, not a decision, so it is in memory and a
        # restart costs one extra round of source queries.
        self._waiting = {}
        # How a cover is fetched, injected so no test reaches the network.
        self.fetch = fetch or fetcher_for()

    @classmethod
    def from_config(cls, config, backups, record=None):
        """The pass this configuration asks for, minus any source it cannot build.

        `record` is Colophon's own record, passed in rather than opened here:
        one connection to one SQLite file is what `Relay` owns, and a second
        opener is how `database is locked` starts.
        """
        sources = []
        for name in config.sources:
            source = _build(name, config)
            if source is not None:
                sources.append(source)
        try:
            llm = Llm.from_config(config)
        except LlmError as error:
            # A name with nowhere to send to, or a key file that cannot be read:
            # a real problem, said as one, and the pass carries on without it.
            LOG.error("%s; carrying on without it", error)
            llm = None
        else:
            if llm is None and needs_key(config.llm_provider):
                # Only a preset that wanted a key and did not get one means the
                # user has simply not set an LLM up. Said once at startup, in the
                # same spirit as "no Hardcover token at …, so hardcover is not
                # asked": a custom endpoint with no key file is being used
                # anyway, and saying "no LLM" about it would be a lie.
                LOG.info(
                    "no LLM key at %s, so uncertain books are marked unverified "
                    "rather than waiting for one",
                    config.llm_key_file,
                )
        return cls(
            sources=sources,
            backups=backups,
            dry_run=config.dry_run,
            fields=config.fields,
            add_cover=config.add_cover,
            strong_score=config.strong_score,
            singleton_score=config.singleton_score,
            medium_score=config.medium_score,
            llm_full_scan=config.llm_full_scan,
            llm=llm,
            record=record,
            overrides=dict(config.authors),
            genres=config.allowed_genres,
        )

    def correct(self, path):
        path = Path(path)
        if path.suffix.lower() not in BOOK_SUFFIXES:
            return Outcome(silent=True)
        # "Wait until tomorrow" is what every wait in this pass means, so this is
        # where the day is allowed to move on: the first book of a new UTC day
        # clears out the books that were left for an older one, and they are
        # asked about again. Done here rather than when an entry is added, so a
        # container that runs for weeks cannot skip a book for the life of the
        # process - and done at a boundary the pass already crosses, so nothing
        # has to run at midnight.
        forget_yesterdays_waits(self._waiting, utc_today())
        note = self._waiting.get(path)
        if note is not None:
            # Already asked for today, and already answered "not today": asking
            # again would spend a source query per scan on a book nothing can
            # finish. The answer still says the book is not finished with, so the
            # relay leaves it where it is - and says nothing, because the first
            # pass said why.
            return Outcome(waiting=True, note=note[1])

        try:
            book = epub.read(path)
        except EpubError as error:
            return Outcome(problem=f"metadata not read: {error}")
        if not self.sources:
            return Outcome(problem="no source is set up, so nothing was looked up")
        if book.isbn:
            return self._by_isbn(path, book)
        return self._by_title(path, book)

    def _by_isbn(self, path, book):
        """The ISBN path, which falls back to the title when the ISBN finds nothing.

        The walk stops at the first source that has the edition. An ISBN
        identifies one, so the first source to know it is as good as any other,
        and the ISBN itself is only ever written by its own rule - usually
        nothing, since the file already carries it.

        No source having the ISBN is not the end of the road. The ISBN a file
        carries can be one no source has - a self-published book, an edition
        Hardcover never listed, or simply a wrong one - and the book is still
        recognisable by its title and its author, which is exactly what the title
        path is for. So the fallback is a title search over the same list, and its
        answer is the answer: a match corrects the book, and nothing at or above
        the threshold leaves it marked unverified like any other book no source
        can vouch for.

        The match the fallback finds keeps the ISBN the file came with: the record
        that recognised the book is a different edition, and writing its ISBN over
        the file's would be claiming an edition this book has not been shown to be.

        A file with no title has nothing to fall back to. The sources were asked
        about it - by its ISBN, which is the one thing the file did say - and none
        of them had it, so the book is marked like any other nobody could vouch
        for. Returning the title path's "no title, so no source was asked" would
        be a plain falsehood on this path: they were asked.
        """
        tried = []
        for source in self.sources:
            tried.append(source.name)
            try:
                found = source.by_isbn(book.isbn)
            except SourceError as error:
                return self._failed(
                    path, [(source.name, str(error))], f"ISBN {book.isbn}"
                )
            if found is not None:
                return self._write(path, found, CONFIDENCE, isbn=book.isbn, book=book)

        if not search_titles(book.title):
            return self._unverified(path, book, None, tried)

        # The book is still recognisable without its ISBN, so the title path
        # answers - whatever it answers. `replace` carries the ISBN the file came
        # with onto that outcome, for the line to name, without claiming it was
        # what recognised the book.
        return replace(self._by_title(path, book), carried_isbn=book.isbn)

    def _by_title(self, path, book):
        """The title path, for a file that carries no ISBN.

        The title is cleaned first, because the file's title has the subtitle
        and the series on it and a source keeps neither. Every configured source
        is asked in turn and every reply joins one pool, which is deduped and
        graded as it then stands: what the first source offered does not decide
        the book on its own, and a source that cannot answer is recorded rather
        than fatal.

        A pool that grades strong ends the walk there, because the sources below
        it were never going to be asked for this book; a pool that does not is
        measured again when the next source's reply joins it. When the sources
        run out with no such decision there is one more thing to try: the LLM
        chooser, which sees the candidates the sources did offer and either picks
        one or says none of them is the book. It is consulted only here, so a
        book the rules already matched never spends a call, and only when there
        is something to put to it. A candidate the rules could not use is still
        offered to the model: they read the title and the author, and the reason
        a book needs an LLM is usually that those two are not enough.

        One rule outranks the band. A walk that *completed* while a configured
        source was erroring is half-asked: it was graded against a pool that is
        missing a source the user put in the trust order, so the book is held
        for tomorrow rather than written or marked (§4.2). A walk that *exited*
        early is not half-asked whatever a source below it might have done - the
        source was never going to be asked.
        """
        titles = search_titles(book.title)
        if not titles:
            return Outcome(problem="no title in the file, so no source was asked")
        title = titles[0]

        # A `dc:language` may be regional (`en-GB`) or three-letter (`eng`); the
        # source indexes editions by the primary code, so that is what is asked.
        language = primary_language(book.language) or None
        # The file's own date is what §2's year field compares, and the sources
        # carry theirs on the candidate. A file with no date simply does not have
        # that field compared, which is why a sparse file is not punished for it.
        file_book = FileBook(book.title, book.authors, language, book.date)
        author = next((name for name in book.authors if str(name).strip()), None)

        walk = self._gather(file_book, titles, language, author, title)
        # The band is not a property of the pool: the thresholds are the user's,
        # so it is asked of them rather than read off the `Ranked`.
        band = band_of(walk.ranked, self.bands)

        if walk.errored and not walk.exited:
            return self._failed(path, walk.errored, title)

        if band == "strong":
            # Both the number and `agrees` are behind this: `band_of` refuses a
            # leader the author gate rejected at every threshold, so a candidate
            # that is not an explanation of this book is never written from on
            # the rules' say-so.
            match = walk.ranked.leader
            return self._write(path, match.candidate, match.score, book=book)

        # The best candidate that does agree on both halves, which is what a
        # book no source could match still names: a reply that agrees on neither
        # is not an explanation of this book and is not named as one, though it
        # is still offered to the model.
        nearest = next((match for match in walk.ranked.matches if match.agrees), None)
        # What the model may be shown. `medium` is the band that was always
        # meant to ask; `llm_full_scan` widens that to low and none, which are
        # the books every source was asked about and nothing usable came back
        # for (§4.3). A strong pool never reaches here.
        offered = top_candidates(walk.ranked)
        if offered and (band == "medium" or self.llm_full_scan):
            chosen, answered = self._ask_llm(path, book, offered)
            if chosen is not None:
                return chosen
            if answered is not None:
                return replace(
                    self._unverified(path, book, title, walk.asked, nearest),
                    llm_pick=answered.pick,
                    llm_confidence=answered.confidence,
                    llm_reason=answered.short_reason,
                )

        # The model was not asked, or answered and was not sure enough, so the
        # book keeps the metadata it came with - and is marked, which is what
        # tells a person browsing their library that nobody could vouch for it.
        # The mark is written here rather than left to the relay, because the
        # correction is the pass that knows what was asked: a book whose walk
        # could not finish is held instead, and a book with no title at all
        # reaches the ISBN path, where the sources were asked and did not have it.
        return self._unverified(path, book, title, walk.asked, nearest)

    def _gather(self, file_book, titles, language, author, title):
        """Ask every source in turn, pool what they offer, and grade the pool.

        Returns the `Walk`: which sources answered, which could not be asked,
        whether the walk stopped on a strong pool, and the pool as it then
        stood. Every error is logged here, once per source rather than once per
        book, because a source that has stopped answering is a problem with the
        run rather than a fact about one book.
        """
        asked = []
        errored = []
        pool = ()
        ranked = Ranked()
        exited = False
        for index, source in enumerate(self.sources):
            try:
                # Every form in one request: a source filters its own way, and
                # the caller's language and author are the filters that keep the
                # reply to this book.
                candidates = source.by_title(list(titles), language, author)
            except SourceError as error:
                errored.append((source.name, str(error)))
                self._blame(source.name, error, title)
                continue
            asked.append(source.name)
            # The pool is built source by source in the order the user ranked
            # them, which is what makes `dedupe`'s first-wins the trust order:
            # the record that survives a group is the one the highest-priority
            # source that offered it sent. Filling in a kept record's missing
            # fields from the others is CBO-61's, not this.
            pool = dedupe([*pool, *candidates])
            ranked = rank(file_book, pool)
            if band_of(ranked, self.bands) == "strong":
                # A source the decision never reached is not a source that
                # failed, which is the whole exemption - and it only means
                # anything when there was one left to reach. A strong pool at the
                # last configured source completed the walk, and that pool is
                # still missing whatever errored.
                exited = index < len(self.sources) - 1
                break

        return Walk(
            asked=tuple(asked),
            errored=tuple(errored),
            exited=exited,
            ranked=ranked,
        )

    def _ask_llm(self, path, book, candidates):
        """Put the candidates to the LLM, and say what it answered.

        Returns `(outcome, choice)`, and the three answers are three of those:
        a pick that clears the threshold is `(the book written, choice)`; a pick
        that is not sure enough, a null pick, or a reply that is not the contract
        at all is `(None, choice)` - the model answered, so there is nothing to
        wait for, and the caller ends it in the unverified path; and not being
        able to ask at all is `(the book left waiting, None)`.

        "Not being able to ask" is not only an outage: the day's call limit is
        spent, and a 4xx that is not a 401 is a configuration mistake that
        repeats every day - both leave the book waiting, deliberately, because
        CBO-43 owns the window and the rejected key.
        """
        if self.llm is None:
            # Not "waiting": a fresh install with no key has nothing to wait for,
            # or every uncertain book would be held for ever (Q16).
            return None, None
        try:
            choice = self.llm.choose(
                {"title": book.title, "filename": path.name}, candidates
            )
        except (LlmError, LlmLimited) as error:
            return self._wait(path, error), None

        if choice.candidate is not None and choice.confidence >= self.strong_score:
            return self._write(
                path, choice.candidate, choice.confidence, book=book, llm=choice
            ), choice
        # A null pick is never applied whatever its confidence says, and a pick
        # the model is not sure of is not applied either. Both are still said:
        # the number is evidence, and the mark is the outcome.
        return None, choice

    def _wait(self, path, error):
        """Leave the book where it is until the next UTC day, and say why.

        Every failure of the LLM's ends here, and the shape of the failure is the
        only thing that differs: an outage is worth waiting out, a rejected key
        is CBO-43's to act on, and a 4xx that is not a 401 repeats every day -
        which is why the LLM logs that last class as a probable misconfiguration
        rather than as an outage.
        """
        LOG.warning(
            "%s is left in the ingest folder until tomorrow: %s", path.name, error
        )
        return self._hold(path, str(error))

    def _hold(self, path, note):
        """Leave a book the pass did not finish with for the next UTC day.

        The file is not written to at all - not even marked - because rewriting
        it in place would change its hash and so its duplicate detection, and the
        whole thing is redone tomorrow. The waiting list is what stops the next
        scan asking the same question again today: it holds the reason, so the
        relay can be told why again without the message being written twice, and
        the day the book was left for, which is what lets the list clear itself
        when tomorrow arrives.
        """
        self._waiting[path] = (utc_today(), note)
        return Outcome(waiting=True, note=note)

    def _unverified(self, path, book, title, tried, nearest=None):
        """Mark a book nothing matched confidently, and say what was looked for.

        The book is written to for the one reason the design spec gives: nobody
        could vouch for its metadata, and a user should be able to find it
        without reading logs. So it is tagged and its description gains the note,
        its own blurb staying where it was, and it is then delivered like any
        other book. A book that was matched later - by being dropped in again -
        has all of this taken off it, which is the other half of the same rule.

        `title` is None for a book whose own title says nothing, which only the
        ISBN path reaches. The book's ISBN is carried onto the outcome either
        way: on that path it is what the sources were asked, so the line names it.
        """
        outcome = self._write(path, None, book=book, isbn=book.isbn or None)
        return replace(
            outcome,
            # A near miss is named as it always was; the title the book was
            # sought under is the fallback when nothing can be named at all, and
            # also when the candidate a source offered has no title to name it by.
            sought=(nearest.candidate.title or title) if nearest is not None else title,
            confidence=nearest.score if nearest is not None else None,
            passed_over=nearest.why if nearest is not None else None,
            tried=tuple(tried),
        )

    def _blame(self, name, error, sought):
        """Say out loud that a source could not be asked about this book.

        Logged at WARNING and not only in the book's own log line, because a
        source being unreachable is a problem with the run rather than a fact
        about one book, and a user watching `docker logs` should not have to read
        every book's line to notice it. Returns the phrase the book's own line
        carries, so the two say the same thing.
        """
        blamed = _label(name)
        LOG.warning(
            "%s could not be asked about %s, so the book is held until tomorrow: %s",
            blamed,
            sought,
            error,
        )
        return f"{blamed} could not be asked: {error}"

    def _failed(self, path, failures, sought):
        """Hold a book whose walk could not be finished, and say which source.

        A book graded against a pool that is missing a source the user
        configured is not a book the rules refused, so nothing about it is
        decided here - not written, not marked, and not put to the model from
        what is left. It is held for the next UTC day instead, which is the same
        answer the LLM's own failures get, for the same reason: the pass did not
        finish, so the book is not the library's yet.

        What happens to it after that - the retry window, and the
        `colophon:source-unavailable` tag - is CBO-43's.
        """
        return self._hold(
            path,
            "; ".join(self._blame(name, error, sought) for name, error in failures),
        )

    def _write(self, path, found, confidence=None, isbn=None, book=None, llm=None):
        """Back the original up, then write what the source is sure of.

        `found` carries the source it came from, so nothing here has to be told
        where the values are from. `isbn` is set only when an ISBN is what
        recognised the book, because that is what the log line then reports.

        `found` is None when no source matched: there is nothing to write from,
        and the only thing this pass has to say is that the book is unverified.
        The rules are not consulted at all in that case, because they are rules
        about a source's values and there are none - and because a book nothing
        could be said about is exactly the book that must be left as it is.

        `book` is the file as it was read, and it is never left out: each rule is
        judged against it, `fill` writes only a field the file is empty of, and
        whether the book already has a cover is a fact about the file.

        `llm` is the model's answer when the model is what chose this record,
        which is the one thing that makes the log line say so: the confidence
        written beside it is the model's own, not `score_candidate`'s, and a
        reader who does not know that would read it as the rules' number.
        """
        unverified = found is None
        # What the log line credits the fields that are not Colophon's own: the
        # source that matched the book. A book nothing matched has no source, and
        # the only thing written to it is the mark, which is Colophon's.
        credited = COLOPHON if unverified else found.source
        # What the library's own record says these names are spelt, applied
        # before anything is decided from them so that the log line, the backup
        # and the book itself all name the same spelling.
        standards = self._standards(found)
        if standards is not None:
            found = standards.applied_to(found)
        edits = self._edits(found, book, unverified=unverified)
        # The genres are mapped before anything is decided, because the answer is
        # part of what the book is written with.
        genres, mappings = (), ()
        if found is not None:
            genres, mappings = self._map_genres(found, book)
            edits = replace(edits, genres=genres)
        matched = {
            "isbn": isbn,
            "sought": None if isbn or unverified else found.title,
            "matched": not unverified,
            "confidence": confidence,
            "source": None if unverified else found.source,
            "unverified": unverified,
            "dry_run": self.dry_run,
        }
        if llm is not None:
            matched.update(
                llm_pick=llm.pick,
                llm_confidence=llm.confidence,
                llm_reason=llm.short_reason,
                chosen_by=LLM_CHOOSER,
            )

        # Ask the file what would move before touching it: a book that already
        # matches is not backed up, and not rewritten either. The cover is asked
        # for only once something is going to be written, because fetching an
        # image for a book about to be left alone is work done for nothing -
        # and a dry run fetches nothing either, for the same reason it writes
        # nothing. What it reports is that a cover would be added, not the image.
        cover = self._cover(path, found, book, would_add=self.dry_run)
        wanted = self._wants_cover(found, book)
        try:
            planned = epub.correct(
                path,
                edits,
                write=False,
                cover=cover,
                would_add_cover=self.dry_run and wanted,
            )
        except EpubError as error:
            # The cover is not an image the file will take. Nothing is written
            # on this pass whatever happens - it only says what would move - so
            # the book is left alone and the reason is said once, here.
            LOG.warning(
                "%s offered a cover for %s that the file would not take, so the "
                "book is corrected without it: %s",
                # `found` is None on the unverified path, and no source offered a
                # cover there: whatever the file refused, Colophon is what wrote
                # it - and a log line is not worth an AttributeError on the one
                # path that must never raise, because the relay would lose the
                # whole scan rather than this book.
                _label(found.source) if found is not None else COLOPHON,
                path.name,
                error,
            )
            planned = ()
            cover = None
        if not planned:
            # Nothing is written, but a genre mapping was still decided: it is a
            # judgement about the source's vocabulary, not a value this pass put
            # on the file, so the record can keep it without the book having been
            # rewritten. Only the genres travel - no resolution and no match -
            # because the book that reaches the library is the one it arrived as.
            # A dry run carries none: an uncached genre was never asked about, so
            # its empty mapping is "not asked" rather than "does not fit".
            return Outcome(
                **matched,
                decision=(
                    Decision(genres=mappings) if mappings and not self.dry_run else None
                ),
            )
        if self.dry_run:
            return Outcome(**matched, changed=_changes(planned, edits, credited))

        try:
            kept = self.backups.keep(path)
        except OSError as error:
            return Outcome(
                **matched,
                changed=_changes(planned, edits, credited),
                problem=f"could not back the original up: {error}",
            )

        try:
            written = epub.correct(path, edits, cover=cover)
        except EpubError:
            # The same cover, refused on the pass that writes. The book is left
            # exactly as it was - `epub.correct` decides everything before it
            # writes anything - so this is the same outcome as a cover that
            # could not be fetched, and the warning above was the saying.
            written = ()
        return Outcome(
            **matched,
            changed=_changes(written, edits, credited),
            applied=True,
            kept=str(kept),
            # Nothing is recorded for a rewrite that was refused: the book that
            # reaches the library is the one it arrived as, so the spelling this
            # pass chose is not one anything on the shelf has.
            decision=(
                self._decision(standards, found, confidence, book, mappings)
                if written
                else None
            ),
        )

    def _map_genres(self, found, book):
        """The allowed genres this book should be given, and how each was decided.

        A genre whose question could not be put - the model is unreachable, its
        key was refused, or the day's calls are spent - is dropped and the book
        lands without it. Nothing is recorded about it either way: it is absent
        rather than decided, so dropping the file in again asks it again. The wait
        belongs to a match the LLM was needed for; a tag on a book the rules
        already resolved is not worth holding that book for a day.

        With no allowed list there is no question to ask at all, so nothing is
        looked up: not the memo, not the record, and not the model. That early
        return is load-bearing, because a memo or a cache hit would otherwise
        hand back a target the empty list cannot accept.

        A genre the book already carries is left out of what is written: the list
        is add-only, so a book that already says `Crime` is not rewritten for it.
        Two source genres that map to one allowed genre are one entry, not two -
        the mapping is still recorded for each of them.
        """
        if not self.allowed_genres:
            return (), ()
        carried = {subject.strip().casefold() for subject in book.subjects}
        wanted = []
        mappings = []
        for genre, seen in found.genres:
            try:
                target = self._one_genre(found.source, genre)
            except (LlmError, LlmLimited) as error:
                LOG.warning(
                    "%s's genre %r could not be asked about, so the book is "
                    "delivered without it and nothing is recorded for it; dropping "
                    "the book in again asks again: %s",
                    found.source,
                    genre,
                    error,
                )
                continue
            mappings.append((found.source, genre, target or "", seen))
            if target and target.strip().casefold() not in carried:
                wanted.append(target)
                carried.add(target.strip().casefold())
        return tuple(wanted), tuple(mappings)

    def _one_genre(self, source, genre):
        """What this source genre maps to, or None, asking only when it must.

        Three places are tried in order, and the first that answers wins: this
        run's own memo, then the record, then the model. A stored target is not
        trusted because it is there - the allowed list may have moved on - so it
        is put through the same membership check a fresh answer is, and a target
        the list no longer holds is a miss rather than an answer.
        """
        key = (source, genre)
        if key in self._genre_memo:
            return self._genre_memo[key]

        if self.record is not None:
            held = self.record.mapping(source, genre)
            if held == "":
                # Asked before, and the answer was that it does not fit.
                return None
            if held is not None:
                target = allowed_spelling(self.allowed_genres, held)
                if target is not None:
                    return target

        if self.llm is None:
            LOG.info(
                "%s's genre %r cannot be mapped: no LLM is set up to judge it, so "
                "the book does not get it",
                source,
                genre,
            )
            return None
        if self.dry_run:
            # A dry run spends no call, so a genre with no stored answer has no
            # answer to report. Saying so is the honest preview; going quiet
            # would read as a book that has no genres.
            LOG.info(
                "dry run: %s's genre %r is not in the record, so whether it maps to "
                "one of the allowed genres was not asked and is not known",
                source,
                genre,
            )
            return None

        target = self.llm.map_genre(self.allowed_genres, genre)
        self._genre_memo[key] = target
        if target is None:
            LOG.info(
                "%s's genre %r does not fit any allowed genre, so the book does not "
                "get it",
                source,
                genre,
            )
        else:
            LOG.info("%s's genre %r is written as %r", source, genre, target)
        return target

    def _standards(self, found):
        """What the record says these names are spelt, or None without one.

        A book nothing matched has no names to standardise, and no record means
        every book keeps the spelling its source gave - which is what every
        version before this one did.
        """
        if found is None or self.record is None:
            return None
        authors = self.record.resolve(
            AUTHOR,
            found.authors,
            found.source,
            identities=found.author_ids,
            overrides=self.overrides,
        )
        if not authors:
            return None
        series = self.record.resolve(
            SERIES,
            [found.series],
            found.source,
            identities=[found.series_id],
            # No overrides: `[authors]` is a table of author spellings. A key
            # only collides with a series name because both are resolved through
            # one normaliser, which is not a reason to rename a series.
        )
        return Standards(
            authors=tuple(one.spelling for one in authors),
            series=series[0].spelling if series else None,
            resolved=authors + series,
        )

    def _decision(self, standards, found, confidence, book, genres=()):
        """What to tell the record once this book has landed, or None.

        Nothing to standardise and nothing mapped means nothing to record. The
        match travels beside the names so a duplicate can be settled later without
        asking the sources again: what recognised the book, how sure it was, and
        the identity it was recognised under.
        """
        if standards is None and not genres:
            return None
        return Decision(
            resolutions=standards.resolved if standards is not None else (),
            match=(
                Match(
                    # The file's own title and authors, not the record's: a book
                    # whose ISBN no source has is recognised by those, and the ones
                    # it is recognised by are the ones the file carries.
                    book_key=book_key(found.isbn, book.title, book.authors),
                    source=found.source,
                    confidence=confidence,
                    matched_as=str(found.isbn or ""),
                )
                if standards is not None
                else None
            ),
            genres=genres,
        )

    def _edits(self, found, book, unverified=False):
        """The fields this source's record is allowed to write, and no others.

        Each field is decided on its own, which is what the config is for: a book
        can take its title from the source and keep its description, and another
        the other way round. `fill` is judged against the file, so a field the
        file already carries is left as it is; `overwrite` writes the source's
        value whenever the source has one.

        A field the source said nothing about is written by no rule at all: `fill`
        on a field a source is silent about is not a blank, and a source with no
        publisher has not offered an empty one.

        `unverified` is the state rather than a value, so it is not a rule: it is
        carried through to the file, which is where the tag and the description
        note are actually written and taken off. Marking a book is the only thing
        a pass with no source writes, so the rules are not consulted for it.
        """
        if unverified:
            # The file's own blurb, because the note goes after it: marking is
            # not a field rule and must not depend on one, so the description is
            # carried as it is and `epub` puts the note on the end of it.
            return Edits(unverified=True, description=book.description)

        # A book that was marked has the note taken off its description before
        # anything is decided: the note is not part of the blurb, and a rule must
        # not be told the book has a blurb when the note is all it has. Stripping
        # it is also half of taking the mark off - `unmarked` of a description
        # that was only the note is None - so `fill` then writes the source's
        # blurb, and `overwrite` writes one over the marked text as it would over
        # any other. The other half, the tag, is `unverified` below.
        marked = book.description if book.unverified else None

        wanted = {}
        for name in KNOWN_FIELDS:
            rule = self.fields.get(name, "skip")
            value = getattr(found, name, None)
            if name == "authors":
                value = tuple(value or ()) or None
            if rule == "skip" or not value:
                continue
            current = getattr(book, name, None)
            if name == "description" and marked:
                current = unmarked(marked)
            if name == "authors":
                current = tuple(current or ())
            if rule == "fill" and current:
                continue
            wanted[name] = value

        if marked and "description" not in wanted:
            # No rule is writing a description, so the one the book has is left
            # in place - with the note off it, which is what this is for; and
            # taken off altogether when that was all it had.
            wanted["description"] = unmarked(marked)
            wanted["notes_taken_off"] = True
            if wanted["description"] is None:
                wanted["drop_description"] = True

        # What this correction is, rather than a value a rule decided: the file
        # and the log line both need to tell a matched book from a marked one
        # without being told twice.
        wanted["unverified"] = False
        return _series_consistent(Edits(**wanted), found, book)

    def _cover(self, path, found, book, would_add=False):
        """The cover to add to this book, or None when there is none to add.

        Only the source that matched is asked for one: the priority list is a
        trust order for every field alike, so a cover may not come from a source
        the user ranked below the one that recognised the book. A source with no
        cover for this book is the ordinary case rather than a failure.

        Fetching can fail, and a cover is the least important thing about a book:
        a blurb and a right title are worth having whether or not the image
        arrives. So a failure here is a line in the log rather than a reason to
        leave the metadata alone.

        `would_add` is a dry run asking whether a cover is on its way without
        wanting the bytes: none are fetched, and `None` is the answer that means
        "not to hand" rather than "none to add".
        """
        if not self._wants_cover(found, book):
            return None
        if would_add:
            return None
        try:
            return self.fetch(found.cover)
        except SourceError as error:
            LOG.warning(
                "%s offered a cover for %s that could not be fetched, so the book "
                "is corrected without it: %s",
                _label(found.source),
                path.name,
                error,
            )
            return None

    def _wants_cover(self, found, book):
        """Whether a cover is to be added to this book, setting and all.

        Three things decide it and nothing else does: the setting is on, the
        source offered one, and the book has none of its own. It is asked
        separately from fetching because a dry run has to answer it without
        fetching anything, and because "no cover to add" and "the bytes are not
        to hand" are different answers with different outcomes.

        `found` is None for a book nothing matched. A book nothing could be said
        about keeps the cover it came with, because there is no source to take
        one from - and taking one off it would be the opposite of leaving it be.
        """
        return bool(
            found is not None and self.add_cover and found.cover and not book.has_cover
        )


def forget_yesterdays_waits(waiting, today):
    """Drop the books that were left for another day than this one.

    A book waiting on a day that has passed is a book nobody has tried since,
    so it is forgotten rather than kept: the whole point of waiting is that
    tomorrow it is worth asking again.
    """
    for path in [path for path, (day, _) in waiting.items() if day != today]:
        del waiting[path]


def _series_consistent(edits, found, book):
    """Keep the number and the series it is a position in from disagreeing.

    A series number is a position in a named series, not a number on its own, so
    the number always follows its series:

    * If the book ends up in the source's series - because the series was
      overwritten, because it was filled in where the file had none, or because
      the file was already in it - the source's number is a position in the
      series the book is in, and its own rule decides whether to write it.
    * If the book ends up in some other series - because the series was skipped,
      or because the source does not name one at all - the source's number is a
      position in a series this book is not in, so it is not written. The number
      the file came with stays where it is, and is dropped only when a series
      was actually written in place of the one around it: a series nobody wrote
      is not a change, so a book with no series name and a number keeps both.

    Both names are compared without regard to case, because a capitalisation
    difference between a file and a record is the same series.

    The question is what the book ends up saying, not which rules were set:
    `overwrite` for the series and `skip` for the number, and `skip` for the
    series and `overwrite` for the number, are the same question asked from
    opposite ends, and both are answered from the resulting pair.
    """
    resulting = edits.series if edits.series is not None else book.series
    if edits.series_number is not None:
        # The source's number, on its way in. It belongs to the source's series,
        # so it is written only if the book ends up in that series.
        if _same_series(resulting, found.series):
            return edits
        return replace(edits, series_number=None)

    # The file's number, being left alone - which is right unless the series
    # around it has actually changed, because then it is a claim about a series
    # this book is no longer in. A series nobody wrote is not a change: a book
    # with no series name and a number keeps both.
    if (
        book.series_number
        and edits.series is not None
        and not _same_series(edits.series, book.series)
    ):
        return replace(edits, drop_series_number=True)
    return edits


def _same_series(one, other):
    """Whether two series names are the same series, capitalisation aside."""
    if not one or not other:
        return False
    return str(one).strip().casefold() == str(other).strip().casefold()


def _build(name, config):
    """The named source, or None if the user has not set its key up.

    A missing key file is not an error: the source is simply not available, and
    the user is told once, at startup, rather than once per book. A key file
    that is there but unreadable is a real problem and is said so.
    """
    entry = SOURCE_SETUP[name]
    where = getattr(config, entry["file"])
    try:
        source = entry["make"](where)
    except SourceError as error:
        LOG.error("%s; carrying on without %s", error, name)
        return None
    if source is None:
        LOG.info(
            "no %s at %s, so %s is not asked and the rest of the list carries on "
            "without it",
            entry["key_label"],
            where,
            name,
        )
    return source


def _label(name):
    """What to call a source in a sentence, as opposed to in a log field.

    A source names itself the way a log field wants it - `hardcover` - and a
    sentence wants it the way a person writes it, which is the label in
    `SOURCE_SETUP`. Every source the corrector can hold came from `from_config`,
    which built it from a name `config.py` had already checked against
    `KNOWN_SOURCES`, so a name that is not in the map is a bug in Colophon rather
    than something a user can cause: it is worth an exception, not a fallback.
    `test_every_configured_source_has_a_label` is what keeps that true.
    """
    return SOURCE_SETUP[name]["label"]


def _names_and_values(changes):
    """The fields that moved, as the log line writes them, and where from.

    A field whose value is long or is bytes is named without it: the line's job
    is which fields moved and who supplied them, and a blurb or a cover written
    into it would bury everything else. Everything else is shown as its value.
    """
    return ", ".join(
        f"{change.field}<-{change.source}"
        if change.field in _NAME_ONLY
        else f'{change.field}="{change.value}"<-{change.source}'
        for change in changes
    )


def _changes(fields, edits, source):
    """The fields that moved, and who moved them.

    Most values come from the source that matched the book. Three do not: the
    tag, the note, and the file's own blurb with the note taken off it when a
    marked book is matched. None of those is anything a source offered, so
    crediting them to `hardcover` would name a source that never saw them - and
    the description is read from the edits, not from `source`, to tell the two
    apart: `Edits.description` is set only when a rule wrote one.
    """
    return tuple(
        Change(field, _value(field, edits), _credited(field, edits, source))
        for field in fields
    )


def _credited(field, edits, source):
    """Who to credit for one field that moved.

    Colophon's own are the tag, and a description it took the note off. The tag
    is always Colophon's - no source supplies one - and the description is a
    source's only when a rule wrote the text being written. `notes_taken_off` is
    what says the description came from the file instead: the text alone cannot,
    because a source repeating the file's own blurb is the same characters as the
    file's own blurb.
    """
    ours = field in ("tag", "genres") or (
        field == "description" and edits.notes_taken_off
    )
    return COLOPHON if ours else source


def _value(field, edits):
    """What a change's value is, for the log line and the outcome alike.

    A field the edits do not carry is one that was written by being taken off -
    a stale series number, a description whose blurb was only ever the note - or
    a cover, which is bytes rather than a value. The tag is the same: it is a
    constant rather than a value carried alongside, and a tag being taken off a
    matched book has no value to report at all.
    """
    if field == "tag":
        return UNVERIFIED_TAG if edits.unverified else ""
    value = getattr(edits, field, None)
    if field in ("authors", "genres"):
        return ", ".join(value or ())
    return "" if value is None else str(value)
