"""CBO-68 session 1b: the band distribution through the real walk, and the three
options simulated. Research probe, not shipped code: nothing in `colophon/` is
changed, and the options are simulated here rather than implemented there.

A snapshot: measured at `22f456b`, before the build. Option 1 here is D3 as it
stood (date, completeness, payload); D15 later put source order before
completeness, and the build's key reads Series Placement conflicts as well, so the
shipped rule is `colophon/matching.standard_editions` and not this one. Re-run
once after the build for the "after" figures (D20).

Run from the repository root:

    python docs/research-cbo-68-probe.py            # everything
    python docs/research-cbo-68-probe.py --shuffle 200

What it does, so every number in docs/research-cbo-68.md §0 can be re-run:

* **The walk is the shipped one.** Each book is an EPUB on disk, read by
  `epub.read`, passed to `Corrector.correct` with `dry_run=True` and `llm=None`
  (a default install with no LLM configured), over the real `Hardcover` and
  `GoogleBooks` clients. Only the transport is replaced.
* **A reply is only replayed for the request it was recorded with.** The
  transport compares the request the client actually sends with
  `tests/recordings.sent_request(row)` for every declared title row, and refuses
  (as a `SourceError`, so the walk records the source as errored) when no
  declared fixture was recorded with that exact request. Nothing is approximated:
  a book whose request no fixture answers says so in the output.
* **The options are simulated by wrapping the pool.** `SimulatedCorrector._gather`
  is the shipped `_gather` with one line changed: the pool passes through the
  option's `transform` before `dedupe`. Option 1 also stops Hardcover
  pre-collapsing by arrival order (D12), by replacing `hardcover._candidates` for
  the duration of the run.

Since the build, D12 is what `hardcover._candidates` does and option 1's rule is
what the shipped `_gather` applies, so the "baseline" column is no longer what
`main` does: it reads option 1's behaviour off the class the option patches. The
shipped figures are measured separately, by the build session.
"""

import argparse
import json
import logging
import random
import sys
import tempfile
import urllib.parse
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from colophon import hardcover as hardcover_module  # noqa: E402
from colophon.backups import Backups  # noqa: E402
from colophon.correction import Corrector, Walk  # noqa: E402
from colophon.googlebooks import GoogleBooks  # noqa: E402
from colophon.hardcover import Hardcover  # noqa: E402
from colophon.matching import (  # noqa: E402
    Ranked,
    _name,
    _parts_of,
    band_of,
    comparison_text,
    dedupe,
    rank,
)
from colophon.sources import SourceError  # noqa: E402
from tests.recordings import RECORDINGS, fixture_path, sent_request  # noqa: E402
from tests.samplebooks import write_epub  # noqa: E402

GUTENBERG = ROOT / "tests" / "fixtures" / "books" / "the-masque-of-the-red-death-epub3.epub"
POE_HAND_MADE = ROOT / "tests" / "fixtures" / "googlebooks" / "hand-made" / "poe-core-cases.json"

# The payload fields D3's tiebreak counts (session 1 §3.2): FIELD_DEFAULTS' nine
# plus the cover.
PAYLOAD = (
    "title", "authors", "series", "series_number", "description",
    "publisher", "date", "isbn", "language", "cover",
)

# ---------------------------------------------------------------- the transports


def _title_rows(source):
    return [r for r in RECORDINGS if r["source"] == source and r["lookup"] == "title"]


class ByRequest:
    """Hands back the declared fixture recorded with exactly this request, or refuses.

    `override` maps a fixture name to a different body path, which is how the
    hand-made Poe case is replayed for the request the live file was made with.
    `shuffle` reorders the reply's list before the client reads it.
    """

    def __init__(self, source, override=None, shuffle=None):
        self.source = source
        self.override = override or {}
        self.shuffle = shuffle
        self.used = []
        self.expected = [(row, sent_request(row)) for row in _title_rows(source)]

    def _body(self, request):
        for row, wanted in self.expected:
            if wanted == request:
                name = row["fixture"]
                # Pairs that share a request are byte-identical (checked by
                # main()), so the first declared row stands for both.
                path = self.override.get(name) or fixture_path(name, self.source)
                self.used.append(str(path.relative_to(ROOT)))
                payload = json.loads(path.read_text(encoding="utf-8"))
                if self.shuffle is not None:
                    listed = (
                        payload.get("items")
                        if self.source == "googlebooks"
                        else payload["data"]["editions"]
                    )
                    if listed:
                        self.shuffle.shuffle(listed)
                return json.dumps(payload).encode("utf-8")
        shown = request.get("variables", request) if self.source == "hardcover" else request.get("q")
        raise SourceError(f"NO RECORDING for {self.source} request {shown}")

    def hardcover(self, url, headers, body):
        return 200, self._body(json.loads(body))

    def google(self, url, headers):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        request = {k: v[0] for k, v in params.items() if k != "key"}
        return 200, self._body(request)


# ---------------------------------------------------------------- the options


def letters(author):
    """D11: symbols may differ, letters may not. The name goes through the
    scorer's own `_name` first (comma reversal, initials joined, accents off), so
    `Ross, L. J.` = `L. J. Ross` = `LJ Ross` = `L.J. Ross`, and `L. K. Ross` is
    someone else."""
    return "".join(ch for ch in _name(author) if ch.isalpha())


def work_key(candidate):
    """The simulated work key: the title head (as the scorer normalises it) and
    every author, compared on letters only (D11). Head-only is refused (D11)."""
    head = comparison_text(_parts_of(candidate.title)[0])
    authors = tuple(sorted(letters(a) for a in candidate.authors))
    return head, authors


def completeness(candidate):
    return sum(1 for f in PAYLOAD if getattr(candidate, f) not in (None, "", ()))


def total_order(candidate):
    """The last resort: the payload itself. Two candidates equal on every payload
    field write the same thing, so which of them survives cannot be observed."""
    return tuple(str(getattr(candidate, f) or "") for f in PAYLOAD)


def standard_edition_key(candidate):
    # Earliest date first (ISO prefixes compare as strings); undated last;
    # then more payload; then the payload itself.
    date = candidate.date or "￿"
    return (date, -completeness(candidate), total_order(candidate))


def option1(candidates):
    """Prefer one edition per work by D3: earliest, then most complete."""
    groups = {}
    order = []
    for c in candidates:
        k = work_key(c)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(c)
    return [min(groups[k], key=standard_edition_key) for k in order]


# The file's year, set by `SimulatedCorrector._gather` for option 1b only.
FILE_YEAR = None


def option1b(candidates):
    """Sensitivity, not a recommendation: option 1, but an edition whose year is
    the file's own `dc:date` year is preferred over the earliest."""
    groups = {}
    order = []
    for c in candidates:
        k = work_key(c)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(c)

    def key(c):
        agrees = FILE_YEAR is not None and (c.date or "")[:4] == FILE_YEAR
        return (0 if agrees else 1, *standard_edition_key(c))

    return [min(groups[k], key=key) for k in order]


def option2(candidates):
    """One work-level candidate per work. Edition fields (ISBN, publisher, the
    edition's date, cover) are not work facts and are dropped. Hardcover's work
    date and blurb are real work fields and are kept (carried in on `_work`);
    Google has no work layer, so its work candidate has no date and no blurb."""
    groups = {}
    order = []
    for c in candidates:
        k = work_key(c)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(c)
    out = []
    for k in order:
        members = groups[k]
        # The identity fields agree within a group by construction of the key,
        # up to spelling; the first member's spelling is taken (which is not
        # deterministic under a shuffled reply: see §0.4).
        first = members[0]
        # The work's own fields exist only where a Hardcover member carried
        # them; a group of Google volumes has none.
        work = next((WORK_FIELDS[id(m)] for m in members if id(m) in WORK_FIELDS), {})
        made = replace(
            first,
            isbn=None,
            publisher=None,
            cover=work.get("cover"),
            date=work.get("date"),
            description=work.get("description"),
        )
        if work:
            WORK_FIELDS[id(made)] = work
        out.append(made)
    return out


# id(candidate) -> the Hardcover work's own fields, filled by the patched
# `_candidates` below so option 2 can read the real work layer.
WORK_FIELDS = {}


@contextmanager
def hardcover_hands_up_every_edition(record_work=False):
    """D12: Hardcover stops pre-collapsing by arrival order."""
    shipped = hardcover_module._candidates

    def every_edition(editions):
        out = []
        for edition in editions:
            c = hardcover_module._candidate(edition)
            if record_work:
                book = edition.get("book") or {}
                WORK_FIELDS[id(c)] = {
                    "date": book.get("release_date"),
                    "description": book.get("description"),
                    "cover": (book.get("image") or {}).get("url"),
                    "book_id": book.get("id"),
                }
            out.append(c)
        return out

    hardcover_module._candidates = every_edition
    try:
        yield
    finally:
        hardcover_module._candidates = shipped


class SimulatedCorrector(Corrector):
    """The shipped corrector; `_gather` is the shipped body with `transform`
    applied to the pool before `dedupe`, and the Walk kept for inspection."""

    transform = None
    last_walk = None

    def _gather(self, file_book, titles, language, author):
        global FILE_YEAR
        FILE_YEAR = (file_book.date or "")[:4] or None
        if self.transform is None:
            walk = super()._gather(file_book, titles, language, author)
            self.last_walk = walk
            return walk
        asked, errored, pool, ranked, exited = [], [], (), Ranked(), False
        for index, source in enumerate(self.sources):
            try:
                candidates = source.by_title(list(titles), language, author)
            except SourceError as error:
                errored.append((source.name, str(error)))
                continue
            asked.append(source.name)
            pool = dedupe(self.transform([*pool, *candidates]))  # the one changed line
            ranked = rank(file_book, pool)
            if band_of(ranked, self.bands) == "strong":
                exited = index < len(self.sources) - 1
                break
        walk = Walk(asked=tuple(asked), errored=tuple(errored), exited=exited, ranked=ranked)
        self.last_walk = walk
        return walk


# ---------------------------------------------------------------- the population

# One file per distinct declared title book. Ross files carry the declared title
# bare, so the request the client builds is exactly the declared one (checked).
# Poe is the real Gutenberg EPUB, whose own title is already bare.
def ross_file(title, author):
    return f"""    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>en</dc:language>
"""


def population(folder):
    books = []
    seen = set()
    for row in RECORDINGS:
        if row["lookup"] != "title":
            continue
        title, author, language = row["book"]
        if (title, author) in seen:
            continue
        seen.add((title, author))
        if author == "Edgar Allan Poe":
            books.append((f"{title} ({author}) [Gutenberg EPUB]", GUTENBERG))
            continue
        if author is None:
            label = f"{title} (no author)"
            meta = f"    <dc:title>{title}</dc:title>\n    <dc:language>en</dc:language>\n"
        else:
            label = f"{title} ({author})"
            meta = ross_file(title, author)
        path = write_epub(folder / f"{len(books):02d}.epub", meta, version="2.0")
        books.append((label, path))
    # The same recorded replies, with the file carrying a year. `dc:date` is
    # not part of either request, so the declared fixture still answers it
    # exactly; only the file differs. 2017 is the original, 2021 the
    # Ulverscroft large print, 2019 neither.
    for year in ("2017", "2021", "2019"):
        meta = ross_file("Cragside", "L. J. Ross") + f"    <dc:date>{year}-01-01</dc:date>\n"
        path = write_epub(folder / f"{len(books):02d}.epub", meta, version="2.0")
        books.append((f"Cragside (L. J. Ross) dc:date={year} [year sensitivity]", path))
    return books


CONFIGS = {
    "hardcover+google (shipped order)": ("hardcover", "googlebooks"),
    "google+hardcover (reversed)": ("googlebooks", "hardcover"),
    "hardcover only": ("hardcover",),
    "google only": ("googlebooks",),
}


def sources_for(names, shuffle=None, override=None):
    made, transports = [], []
    for name in names:
        t = ByRequest(name, override=override, shuffle=shuffle)
        transports.append(t)
        if name == "hardcover":
            made.append(Hardcover("TOKEN", transport=t.hardcover))
        else:
            made.append(GoogleBooks("KEY", transport=t.google))
    return made, transports


def run_one(path, names, transform, folder, shuffle=None, override=None):
    WORK_FIELDS.clear()
    sources, transports = sources_for(names, shuffle=shuffle, override=override)
    corrector = SimulatedCorrector(
        sources=sources,
        backups=Backups(folder / "backups"),
        dry_run=True,
        llm=None,
        fetch=lambda url: (_ for _ in ()).throw(SourceError("offline")),
    )
    corrector.transform = transform
    outcome = corrector.correct(path)
    walk = corrector.last_walk
    used = [u for t in transports for u in t.used]
    return outcome, walk, used


# Volume / edition labels, so a candidate is named rather than counted.
def _labels():
    labels = {}
    for f in (ROOT / "tests" / "fixtures" / "googlebooks").glob("by-title-*.json"):
        for item in json.loads(f.read_text(encoding="utf-8")).get("items") or []:
            for ident in item["volumeInfo"].get("industryIdentifiers") or []:
                labels[("google_books", ident["identifier"])] = item["id"]
            info = item["volumeInfo"]
            labels[("google_books", info.get("title"), info.get("publishedDate"))] = item["id"]
    for item in json.loads(POE_HAND_MADE.read_text(encoding="utf-8"))["items"]:
        for ident in item["volumeInfo"].get("industryIdentifiers") or []:
            labels[("google_books", ident["identifier"])] = item["id"]
    return labels


LABELS = _labels()


def name(candidate):
    tag = LABELS.get((candidate.source, candidate.isbn)) or (
        LABELS.get((candidate.source, candidate.title, candidate.date)) if candidate.isbn is None else None
    )
    who = f"{candidate.source}:{tag or candidate.isbn or '-'}"
    return f"{who} {candidate.date or 'undated'} {candidate.title!r}/{'; '.join(candidate.authors)}"


def describe(walk):
    if walk is None:
        return "no walk", [], None
    ranked = walk.ranked
    matches = ranked.matches
    band = band_of(ranked)
    tied = [m for m in matches if matches and m.score == matches[0].score]
    return band, tied, ranked


OPTIONS = {
    "baseline (= option 3, keep unverified)": (None, None),
    "option 1 (standard edition: earliest, then completeness)": (option1, "every_edition"),
    "option 2 (work-level candidate)": (option2, "every_edition_with_work"),
    "option 1b (sensitivity: the file's year first, then option 1)": (option1b, "every_edition"),
}


def main():
    # The walk logs every held book; the probe prints its own account instead.
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser()
    parser.add_argument("--shuffle", type=int, default=100, help="shuffled runs per book")
    args = parser.parse_args()

    # The byte-identical pairs the transport lets one row stand for.
    for src, a, b in (
        ("hardcover", "by-title-cragside.json", "by-title-cragside-other-fields.json"),
        ("hardcover", "by-title-the-infirmary.json", "by-title-the-infirmary-other-fields.json"),
        ("googlebooks", "by-title-cragside.json", "by-title-cragside-other-fields.json"),
    ):
        same = fixture_path(a, src).read_bytes() == fixture_path(b, src).read_bytes()
        print(f"pair {src}/{a} == {b}: {same}")

    # Step 3: does Hardcover's `book.id` already give the grouping, and does it
    # agree with the synthesized key on every Hardcover title fixture?
    print("\nbook.id against work_key, every edition in every hardcover title fixture:")
    for row in _title_rows("hardcover"):
        path = fixture_path(row["fixture"], "hardcover")
        editions = json.loads(path.read_text(encoding="utf-8"))["data"]["editions"]
        by_id, by_key = {}, {}
        for i, edition in enumerate(editions):
            c = hardcover_module._candidate(edition)
            by_id.setdefault((edition.get("book") or {}).get("id"), set()).add(i)
            by_key.setdefault(work_key(c), set()).add(i)
        same = sorted(map(sorted, by_id.values())) == sorted(map(sorted, by_key.values()))
        print(f"  {row['fixture']}: {len(editions)} editions; book.id groups "
              f"{ {k: sorted(v) for k, v in by_id.items()} }; key groups agree: {same}")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        books = population(folder)
        for option, (transform, patch) in OPTIONS.items():
            print(f"\n######## {option}")
            for config, names in CONFIGS.items():
                print(f"\n== {config}")
                counts = {}
                for label, path in books:
                    ctx = (
                        hardcover_hands_up_every_edition(record_work=(patch == "every_edition_with_work"))
                        if patch
                        else _null()
                    )
                    with ctx:
                        outcome, walk, used = run_one(path, names, transform, folder)
                        band, tied, ranked = describe(walk)
                        # Determinism: shuffle every reply, compare band and
                        # the written payload of the leader.
                        base = (band, _payload(ranked))
                        seen = {base}
                        rng = random.Random(68)
                        for _ in range(args.shuffle):
                            _, w2, _ = run_one(path, names, transform, folder, shuffle=rng)
                            b2, _, r2 = describe(w2)
                            seen.add((b2, _payload(r2)))
                    counts[band] = counts.get(band, 0) + 1
                    verdict = (
                        "matched" if outcome.matched
                        else "UNVERIFIED" if outcome.unverified
                        else ("problem: " + str(outcome.problem)) if outcome.problem
                        else "held/other"
                    )
                    errored = [e for e in (walk.errored if walk else ())]
                    print(f"  {label}: band={band} -> {verdict}; pool={len(ranked.matches) if ranked else 0}; "
                          f"asked={list(walk.asked) if walk else []}; exited={walk.exited if walk else None}; "
                          f"distinct outcomes over {args.shuffle} shuffles={len(seen)}")
                    for e in errored:
                        print(f"      errored: {e[0]}: {e[1][:120]}")
                    print(f"      replayed: {used}")
                    if ranked and ranked.matches:
                        m = ranked.matches
                        print(f"      leader {m[0].score:.4f} {name(m[0].candidate)}")
                        if len(m) > 1:
                            print(f"      runner-up {m[1].score:.4f} {name(m[1].candidate)}; gap {ranked.gap:.4f}")
                        if len(tied) > 1:
                            print(f"      tied at {m[0].score:.4f}: " + " | ".join(name(t.candidate) for t in tied))
                        for extra in m[2:]:
                            print(f"        also {extra.score:.4f} {name(extra.candidate)}")
                print(f"  -> {dict(sorted(counts.items()))}")

        # The hand-made Poe tie, replayed for the request the live file answers.
        print("\n######## hand-made/poe-core-cases.json, google only")
        override = {"by-title-poe.json": POE_HAND_MADE}
        for option, (transform, patch) in OPTIONS.items():
            ctx = hardcover_hands_up_every_edition(patch == "every_edition_with_work") if patch else _null()
            with ctx:
                outcome, walk, used = run_one(GUTENBERG, ("googlebooks",), transform, folder, override=override)
                band, tied, ranked = describe(walk)
                seen = {(band, _payload(ranked))}
                rng = random.Random(69)
                for _ in range(args.shuffle):
                    _, w2, _ = run_one(GUTENBERG, ("googlebooks",), transform, folder, shuffle=rng, override=override)
                    b2, _, r2 = describe(w2)
                    seen.add((b2, _payload(r2)))
            print(f"  {option}: band={band}; pool={len(ranked.matches)}; distinct over shuffles={len(seen)}; replayed {used}")
            for m in ranked.matches:
                print(f"      {m.score:.4f} {name(m.candidate)}")

        # CBO-75: the hand-made volumes still carry `subtitle` (they predate the
        # mask). If `_candidate` joined it onto the title, does option 1 group
        # or grade differently?
        print("\n######## CBO-75: hand-made Poe with the subtitle joined onto the title")
        from colophon import googlebooks as google_module

        shipped = google_module._candidate

        def joined(volume):
            c = shipped(volume)
            sub = (volume.get("volumeInfo") or {}).get("subtitle")
            return replace(c, title=f"{c.title}: {sub}") if sub else c

        google_module._candidate = joined
        try:
            for option, (transform, patch) in OPTIONS.items():
                outcome, walk, used = run_one(GUTENBERG, ("googlebooks",), transform, folder, override=override)
                band, tied, ranked = describe(walk)
                print(f"  {option}: band={band}; pool={len(ranked.matches)}")
                for m in ranked.matches:
                    print(f"      {m.score:.4f} {m.title_reason} {name(m.candidate)}")
        finally:
            google_module._candidate = shipped


def _payload(ranked):
    if ranked is None or not ranked.matches:
        return None
    return total_order(ranked.matches[0].candidate)


@contextmanager
def _null():
    yield


if __name__ == "__main__":
    main()
