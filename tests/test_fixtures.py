"""The guard that fails when a fixture's field set is not its query's.

The claim is narrow, and everything this module refuses to do follows from it:
**a committed fixture matches the query that would produce it today.** Not "the
fixture is well formed", not "the client reads every field it fetched" — the second
is CBO-73's guard, and a third claim, whether the source still answers what it used
to, cannot be checked without a live recording.

A fixture whose keys have stopped agreeing with its declared query is a recording
of a request the client no longer makes, and every measurement taken from it
describes a reply nobody can obtain. That is the whole defect CBO-74 exists for.

The query a fixture was made with is declared in `tests/recordings.py`, which is
also what `Replay`/`ReplayByQuery` use. This reads the same declaration, so the
fixture, the replay and the guard cannot disagree about which query produced a
file.
"""

import json
import re
import unittest

from tests import recordings

# ---------------------------------------------------------------------------
# Reading a query's selection set
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"\s+|#[^\n]*|[,{}()]|[^\s,{}()]+")


def tokenize(query):
    """A query as words and punctuation, with whitespace and comments dropped."""
    return [
        match.group()
        for match in _TOKEN.finditer(query)
        if not match.group().isspace() and not match.group().startswith("#")
    ]


def parse_selection(query):
    """A GraphQL query's selection as nested dicts, keyed from the root field down.

    A leaf is `{}`. The three field shapes are `title`, `publisher { name }` and
    `contributions(where: {...}) { author { id } }`, and reading it as a grammar is
    the only way to get the third right: a character-by-character reader has to
    guess whether a name is about to be followed by arguments, a selection, or
    neither, and the guess is wrong for at least one of the three.

    `test_hardcover.selection_set` reads one level and returns a string, which was
    enough while the only drift was edition-level. The fields that actually drifted
    are nested — `cached_tags`, `book.id`, `author.id`, `series.id` — and a
    single-level reader cannot tell `book { title }` from `book { title id }`.
    """
    tokens = tokenize(query)
    if "{" not in tokens:
        return {}
    tree, _ = parse_fields(tokens, tokens.index("{") + 1)
    return tree


def parse_fields(tokens, at):
    """One selection set, from just after its `{` to just before its `}`."""
    fields = {}
    while at < len(tokens) and tokens[at] != "}":
        if tokens[at] == ",":
            at += 1
            continue
        name = tokens[at]
        at += 1
        if at < len(tokens) and tokens[at] == "(":
            at = skip_arguments(tokens, at)
        if at < len(tokens) and tokens[at] == "{":
            fields[name], at = parse_fields(tokens, at + 1)
        else:
            fields[name] = {}
    return fields, at + 1


def skip_arguments(tokens, at):
    """Past the `(...)` starting at `at`, nested filter braces and all.

    Arguments are removed rather than kept, for the reason CBO-73 gives: `QUERY`
    filters on `isbn_13` while selecting it, so a reader that cannot tell a field
    that is fetched from one that is merely filtered on passes a query that returns
    no ISBN while reading as correct.
    """
    depth = 0
    while at < len(tokens):
        if tokens[at] == "(":
            depth += 1
        elif tokens[at] == ")":
            depth -= 1
            if depth == 0:
                return at + 1
        at += 1
    return at


def selected_paths(tree, prefix=""):
    """Every field path a selection names, parents and leaves alike."""
    found = set()
    for name, nested in tree.items():
        found.add(prefix + name)
        found |= selected_paths(nested, prefix + name + ".")
    return found


def selected_leaves(tree, prefix=""):
    """The paths of fields with no selection of their own.

    A leaf's value is the source's to shape: the queries ask for `cached_tags`
    whole because a jsonb column's inner keys are not selectable one at a time, and
    for `imageLinks` whole because Google nests two sizes in it. Whatever is inside
    one of those is not a key the query failed to name, so nothing under a leaf is
    ever a complaint.
    """
    found = set()
    for name, nested in tree.items():
        if nested:
            found |= selected_leaves(nested, prefix + name + ".")
        else:
            found.add(prefix + name)
    return found


def google_selection(mask):
    """Google's `fields` mask as a selection tree, in the reply's own terms.

    The mask is an enumeration of paths (`items/volumeInfo/title`) rather than a
    GraphQL selection, and it is genuinely closed: anything outside it is not
    returned at all. So the same comparison works, with one difference — the paths
    run from the reply's top level down, and `items` is a list of volumes rather
    than a single object.
    """
    tree = {}
    for part in mask.split(","):
        parts = [step for step in part.strip().split("/") if step]
        node = tree
        for step in parts:
            node = node.setdefault(step, {})
    return tree


# ---------------------------------------------------------------------------
# Reading a fixture's key paths
# ---------------------------------------------------------------------------


def payload_paths(value, prefix=""):
    """Every key path a payload carries, descending only where the source nested."""
    found = set()
    if isinstance(value, list):
        for item in value:
            found |= payload_paths(item, prefix)
        return found
    if not isinstance(value, dict):
        return found
    for key, item in value.items():
        found.add(prefix + key)
        if isinstance(item, (dict, list)) and item:
            found |= payload_paths(item, prefix + key + ".")
    return found


def records_of(source, body):
    """A reply's records: one per edition for Hardcover, one per volume for Google."""
    if source == "hardcover":
        data = body.get("data")
        return (data or {}).get("editions") or [] if isinstance(data, dict) else []
    return body.get("items") or []


def volume_prefix(source):
    """Where a reply's records sit, as a path prefix."""
    return "" if source == "hardcover" else "items."


# ---------------------------------------------------------------------------
# The three legitimate mismatches, each exempt by name
# ---------------------------------------------------------------------------

# A key the query selects that no record carries, and the source is why. The
# first of the three the ticket names. `by-title-belsay.json` is the specimen the
# ticket cites: the query asks for the ISBNs, Hardcover has none for that edition,
# and the reply simply does not carry the key. That is not drift, and a guard that
# failed on it would be red on a correct fixture.
NULL_BUT_SELECTED = {
    ("hardcover", "by-title-belsay.json", "publisher.name"): (
        "Hardcover has no publisher for this edition, so the reply carries no "
        "`publisher` object; the query asks for one"
    ),
    ("googlebooks", "by-title-poe.json", "volumeInfo.categories"): (
        "not one of the twenty volumes is categorised, so the masked reply omits "
        "the key entirely"
    ),
    ("googlebooks", "by-title-poe.json", "volumeInfo.publisher"): (
        "Google has no publisher for the editions in this reply"
    ),
    ("googlebooks", "by-title-the-infirmary.json", "volumeInfo.publisher"): (
        "Google has no publisher for this volume"
    ),
    ("googlebooks", "by-isbn-cragside.json", "volumeInfo.imageLinks"): (
        "the volume has no cover, which is the case that fixture exists for"
    ),
    ("googlebooks", "by-isbn-cragside.json", "volumeInfo.publisher"): (
        "Google has no publisher for this volume"
    ),
    ("googlebooks", "by-isbn-cragside-other-fields.json", "volumeInfo.imageLinks"): (
        "the same absent cover, on the recording CBO-38 made for these fields"
    ),
    (
        "googlebooks",
        "by-isbn-cragside-other-fields.json",
        "volumeInfo.publisher",
    ): "the same absent publisher",
    ("googlebooks", "by-isbn-cragside-authors.json", "volumeInfo.imageLinks"): (
        "the same absent cover, on CBO-41's recording"
    ),
    ("googlebooks", "by-isbn-cragside-authors.json", "volumeInfo.publisher"): (
        "the same absent publisher"
    ),
    ("googlebooks", "isbn-cragside-categories.json", "volumeInfo.imageLinks"): (
        "the same absent cover, on CBO-42's recording"
    ),
    ("googlebooks", "isbn-cragside-categories.json", "volumeInfo.publisher"): (
        "the same absent publisher"
    ),
    ("googlebooks", "by-isbn-one-digit-off.json", "volumeInfo.imageLinks"): (
        "the volume Google answered with has no cover"
    ),
    ("googlebooks", "by-isbn-one-digit-off.json", "volumeInfo.publisher"): (
        "and no publisher"
    ),
    # A standalone book has no series, so Hardcover sends no `book_series` at all.
    # Five paths rather than one because the selection reaches through the
    # membership to the series; the absent object is the whole of it.
    ("hardcover", "by-isbn-no-series.json", "book.book_series"): (
        "Normal People is a standalone book, so there is no membership to carry"
    ),
    ("hardcover", "by-isbn-no-series.json", "book.book_series.featured"): (
        "no membership, so nothing to mark featured"
    ),
    ("hardcover", "by-isbn-no-series.json", "book.book_series.position"): (
        "no membership, so no position in it"
    ),
    ("hardcover", "by-isbn-no-series.json", "book.book_series.series"): (
        "no membership, so no series row"
    ),
    ("hardcover", "by-isbn-no-series.json", "book.book_series.series.id"): (
        "no series row, so no id"
    ),
    ("hardcover", "by-isbn-no-series.json", "book.book_series.series.name"): (
        "no series row, so no name"
    ),
}

# A key a fixture carries and the query does not select, because the query selected
# it when the recording was made. The second of the three. This is drift and it is
# the class the guard exists for, so nothing is exempt here: the entry is empty on
# purpose, and a fixture landing in it is re-recorded rather than listed.
FORMERLY_SELECTED = {}

# A fixture deliberately recorded off-spec, where "the query that would produce it
# today" is not the question the file answers. The third of the three, and it is
# empty because the one candidate turned out not to be off-spec: the re-record
# showed Hardcover returns the featured series first whether or not the query asks
# it to, so `by-isbn-two-series.json` is an ordinary live recording. See
# `fixtures/hardcover/README.md`.
OFF_SPEC = {}


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------


def complaints(row, body):
    """Every way this body fails to match the query its row declares."""
    source, fixture = row["source"], row["fixture"]
    records = records_of(source, body)
    if not records:
        # An empty reply has no shape to disagree with a field list: both sources
        # answer empty as `{"totalItems": 0}` or `{"data": {"editions": []}}`, and
        # there is nothing in either to compare. The fixtures that are empty are
        # named in `tests/recordings.py` rather than silently skipped here.
        return []

    request = recordings.sent_request(row)
    if source == "hardcover":
        selection = next(iter(parse_selection(request["query"]).values()), {})
        carried_top = set(body)
        expected_top = {"data"}
    else:
        # The mask names whole paths, so its tree starts at the reply's top level
        # and `items` is a list of volumes rather than one object.
        selection = parse_selection_mask(request["fields"])
        volumes = selection.pop("items", {})
        carried_top = {key for key in body if key != "items"}
        expected_top = set(selection)
        selection = volumes

    prefix = volume_prefix(source)
    selected = {prefix + path for path in selected_paths(selection)}
    leaves = {prefix + path for path in selected_leaves(selection)}
    carried = {prefix + path for path in payload_paths(records[0])}

    found = []
    for path in sorted(carried_top - expected_top):
        found.append(f"{path}: carried and not selected")
    for path in sorted(expected_top - carried_top):
        found.append(f"{path}: selected and not carried")
    for path in sorted(carried - selected):
        if not under_a_leaf(path, leaves):
            found.append(f"{path}: carried and not selected")
    for path in sorted(selected - carried):
        if (source, fixture, path[len(prefix) :]) in NULL_BUT_SELECTED:
            continue
        if under_a_leaf(path, leaves):
            continue
        found.append(f"{path}: selected and not carried")
    return found


def parse_selection_mask(mask):
    """The same tree for Google's mask, which names whole paths rather than nesting."""
    return google_selection(mask)


def under_a_leaf(path, leaves):
    """Whether this path is inside a selected field that has no selection of its own."""
    return any(path.startswith(leaf + ".") for leaf in leaves)


class SelectionParserTests(unittest.TestCase):
    """The parser, on the three field shapes and on CBO-73's trap."""

    def test_a_bare_field_is_a_leaf(self):
        self.assertEqual(
            parse_selection("query Q { editions { title } }"),
            {"editions": {"title": {}}},
        )

    def test_a_field_with_arguments_and_a_selection_is_a_parent(self):
        """The shape every character-by-character reading of this got wrong."""
        parsed = parse_selection(
            "query Q($i: String!) {\n"
            "  editions(where: {_or: [{isbn_13: {_eq: $i}}]}, limit: 1) {\n"
            "    isbn_13\n"
            "  }\n"
            "}"
        )

        self.assertEqual(parsed, {"editions": {"isbn_13": {}}})

    def test_a_field_with_arguments_and_no_selection_is_a_leaf(self):
        self.assertEqual(
            parse_selection("query Q($i: String!) { editions(limit: 1) { title } }"),
            {"editions": {"title": {}}},
        )

    def test_arguments_are_skipped_whole(self):
        """CBO-73's shape: a field filtered on must not read as a field fetched."""
        parsed = parse_selection(
            "query Q($i: String!) { editions(where: {isbn_13: {_eq: $i}}) { title } }"
        )

        self.assertEqual(parsed, {"editions": {"title": {}}})
        self.assertNotIn("isbn_13", selected_paths(parsed))

    def test_comments_are_not_fields(self):
        """Both shipped queries are commented."""
        parsed = parse_selection(
            "query Q {\n  editions {\n    # Asked whole: a jsonb column\n    cached_tags\n  }\n}"
        )

        self.assertEqual(parsed, {"editions": {"cached_tags": {}}})

    def test_the_two_shipped_queries_differ_where_they_really_differ(self):
        """`book.id` is the field CBO-73 restored to one query and not the other."""
        from colophon import hardcover

        isbn = selected_paths(parse_selection(hardcover.QUERY))
        title = selected_paths(parse_selection(hardcover.TITLE_QUERY))

        self.assertIn("editions.book.id", title)
        self.assertNotIn("editions.book.id", isbn)
        self.assertIn("editions.book.cached_tags", isbn)
        self.assertIn("editions.book.contributions.author.id", title)
        self.assertIn("editions.book.book_series.series.id", title)

    def test_a_jsonb_column_is_a_leaf_so_its_inner_keys_are_not_expected(self):
        """`cached_tags` is asked for whole; its four categories are the schema's."""
        from colophon import hardcover

        leaves = selected_leaves(parse_selection(hardcover.QUERY))

        self.assertIn("editions.book.cached_tags", leaves)
        self.assertIn("editions.image.url", leaves)


class GoogleMaskTests(unittest.TestCase):
    """The mask is an enumeration of whole paths rather than a nested selection."""

    def test_it_reads_the_mask_as_the_paths_it_names(self):
        mask = google_selection("totalItems,items/id,items/volumeInfo/title")

        self.assertEqual(
            mask,
            {"totalItems": {}, "items": {"id": {}, "volumeInfo": {"title": {}}}},
        )

    def test_the_shipped_mask_asks_for_the_categories(self):
        """`googlebooks/README.md:139-154` said otherwise; the code was right."""
        from colophon import googlebooks

        self.assertIn(
            "volumeInfo.categories",
            selected_paths(google_selection(googlebooks.FIELDS)["items"]),
        )


class DriftTests(unittest.TestCase):
    """The guard on fixtures that are wrong on purpose.

    These are built here rather than committed, because a committed drifted
    fixture is the defect the guard exists to catch. Each one is the real corpus
    with exactly one thing changed.
    """

    def row(self, source, fixture):
        return next(
            row
            for row in recordings.RECORDINGS
            if row["source"] == source and row["fixture"] == fixture
        )

    def body(self, source, fixture):
        return json.loads(
            (recordings.FIXTURE_ROOT / source / fixture).read_text("utf-8")
        )

    def test_a_clean_fixture_has_nothing_to_say(self):
        row = self.row("hardcover", "by-isbn-cragside-edition.json")

        self.assertEqual(complaints(row, self.body(row["source"], row["fixture"])), [])

    def test_a_fixture_carrying_a_key_the_query_stopped_selecting_fails(self):
        """The CBO-73 shape: a recording of a request the client no longer makes."""
        row = self.row("hardcover", "by-isbn-cragside-edition.json")
        body = self.body(row["source"], row["fixture"])
        body["data"]["editions"][0]["book"]["id"] = 1198994

        found = complaints(row, body)

        self.assertIn("book.id: carried and not selected", found)

    def test_a_nested_key_the_query_stopped_selecting_fails_too(self):
        """`author.id` is one level further down, and top-level-only would miss it."""
        row = self.row("hardcover", "by-isbn-cragside-edition.json")
        body = self.body(row["source"], row["fixture"])
        body["data"]["editions"][0]["book"]["contributions"][0]["author"][
            "canonical_id"
        ] = 1

        found = complaints(row, body)

        self.assertIn(
            "book.contributions.author.canonical_id: carried and not selected", found
        )

    def test_a_fixture_missing_a_selected_key_fails(self):
        row = self.row("hardcover", "by-isbn-cragside-edition.json")
        body = self.body(row["source"], row["fixture"])
        del body["data"]["editions"][0]["isbn_13"]

        found = complaints(row, body)

        self.assertIn("isbn_13: selected and not carried", found)

    def test_a_google_fixture_recorded_without_the_mask_fails(self):
        """The whole shape of the ten unmasked recordings the ticket found."""
        row = self.row("googlebooks", "by-isbn-cragside.json")
        body = self.body(row["source"], row["fixture"])
        body["kind"] = "books#volumes"
        body["items"][0]["kind"] = "books#volume"
        body["items"][0]["saleInfo"] = {"country": "GB"}

        found = complaints(row, body)

        self.assertIn("kind: carried and not selected", found)
        self.assertIn("items.kind: carried and not selected", found)
        self.assertIn("items.saleInfo: carried and not selected", found)


class CorpusTests(unittest.TestCase):
    """Every declared fixture in the committed corpus matches its declared query."""

    def test_no_fixture_disagrees_with_the_query_that_would_produce_it(self):
        failures = []
        for row in recordings.RECORDINGS:
            path = recordings.fixture_path(row["fixture"], row["source"])
            body = json.loads(path.read_text("utf-8"))
            for complaint in complaints(row, body):
                failures.append(f"{row['source']}/{row['fixture']}: {complaint}")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_every_fixture_is_either_declared_or_named_as_having_no_query(self):
        """A new fixture cannot be added quietly: it needs a row or a reason."""
        undeclared = [
            f"{source}/{fixture}"
            for source, fixture, row, reason in recordings.declarations()
            if row is None and reason is None
        ]

        self.assertEqual(undeclared, [])


if __name__ == "__main__":
    unittest.main()
