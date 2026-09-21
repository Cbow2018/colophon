"""Tests for title cleaning, comparison normalisation and the graded score.

The design is `docs/research/cbo-58.md`. Every expected number below is read out
of one of its tables - §2.1 (the weights against the real cases), §2.2 (the
regression against the shipped rule), §3.2 (the similarity calibration), §3.4
(names) or §4.1 (the bands) - and the comment on each assertion says which.
None of them was read off the implementation, and none was moved to match it.
"""

import unittest
from itertools import pairwise

from colophon.matching import (
    AUTHOR_AGREES,
    NO_AGREEMENT_CEILING,
    Bands,
    Candidate,
    FileBook,
    band_of,
    clean_title,
    comparison_text,
    dedupe,
    normalise,
    rank,
    score_candidate,
    search_title,
    top_candidates,
)

MESSY = "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)"
BARE = "Cragside"
LJ = ("L. J. Ross",)
THE_INFIRMARY_FILE = "The Infirmary: A DCI Ryan Mystery"

# §2's weights, as the four denominators §2.1's rows read off them: 2.15 with
# every field, 2.00 (row 2, no year), 1.80 (row 8, title and author), 1.35
# (row 10, title, series and year) and 1.00 (row 7, the title alone).
ALL_FOUR = 2.15
NO_YEAR = 2.00
TITLE_AUTHOR = 1.80
TITLE_SERIES_YEAR = 1.35
TITLE_ALONE = 1.00
TITLE_SERIES = 1.35

# §2's weights, spelled once so the expected scores below can be written as the
# arithmetic §2 gives rather than as decimals copied from a run.
TITLE_W, AUTHOR_W, SERIES_W, YEAR_W = 1.00, 0.80, 0.20, 0.15

# §3.2's calibration, as the note gives it: the anchors, the dead band at the
# top and the floor at the bottom. `penalty(raw)` is what §2's accumulator
# multiplies by the field's weight, so every score below can be written as
# `1 - Σ(weight × penalty) / denominator` and checked by hand. Where a test
# compares two synthetic runs of `n` and `m` identical characters, the ratio is
# exact by construction: the longest match is the shorter run, so it is `2m/(n +
# m)` — and the article rule leaves the shortest run alone, which is the 0.375
# §3.2's floor test needs.
STRETCH = (
    (0.35, 1.00),
    (0.50, 0.88),
    (0.60, 0.78),
    (0.70, 0.63),
    (0.80, 0.45),
    (0.90, 0.22),
    (1.00, 0.00),
)
DEAD_BAND = 0.97
FLOOR = 0.35


def penalty(raw):
    """§3.2's curve: dead band, floor, straight lines between the anchors."""
    if raw >= DEAD_BAND:
        return 0.0
    if raw < FLOOR:
        return 1.0
    for (low_raw, low), (high_raw, high) in pairwise(STRETCH):
        if low_raw <= raw <= high_raw:
            return low + ((raw - low_raw) / (high_raw - low_raw)) * (high - low)
    return 1.0


def candidate(title=None, authors=LJ, series_number=None, date=None, **rest):
    """One record, with the fields §2.1's fixture rows use."""
    return Candidate(
        title=title, authors=authors, series_number=series_number, date=date, **rest
    )


CRAGSIDE_RECORD = candidate(title="Cragside", series_number="6", date="2017-07-07")


class ComparisonTextTests(unittest.TestCase):
    """§3.1's pipeline, step for step."""

    def test_accented_letters_reach_the_same_key_as_unaccented_ones(self):
        """§3.1 steps 1-2: NFKD splits the accent off, and the mark is dropped."""
        self.assertEqual(comparison_text("Brontë"), "bronte")
        self.assertEqual(comparison_text("Charlotte Brontë"), "charlotte bronte")
        self.assertEqual(comparison_text("Brontë"), comparison_text("Bronte"))

    def test_case_is_folded_the_unicode_way(self):
        """§3.1 step 3: `casefold`, not `lower` - the German ß is what that buys."""
        self.assertEqual(comparison_text("STRASSE"), "strasse")
        self.assertEqual(comparison_text("Straße"), "strasse")

    def test_an_ampersand_is_the_word_and(self):
        """§3.1 step 4."""
        self.assertEqual(
            comparison_text("The Wind & the Willows"),
            comparison_text("The Wind and the Willows"),
        )

    def test_punctuation_is_a_word_break_and_runs_collapse(self):
        """§3.1 step 5: `don't` compares as `don t`, and a symbol leaves one space."""
        self.assertEqual(comparison_text("The Waste Land."), "waste land")
        self.assertEqual(comparison_text("The Waste-Land"), "waste land")
        self.assertEqual(comparison_text("don't"), "don t")

    def test_a_leading_article_goes_only_when_two_tokens_are_left(self):
        """§3.1 step 6 and its guard: `The Infirmary` keeps its article."""
        self.assertEqual(comparison_text("The Waste Land"), "waste land")
        self.assertEqual(comparison_text("The Infirmary"), "the infirmary")
        self.assertEqual(comparison_text("A"), "a")
        self.assertEqual(comparison_text("An Old Series"), "old series")

    def test_the_result_is_stripped(self):
        """§3.1 step 7."""
        self.assertEqual(comparison_text("  Cragside  "), "cragside")
        self.assertEqual(comparison_text("Cragside!"), "cragside")

    def test_an_empty_or_missing_text_is_an_empty_key(self):
        for text in (None, "", "   ", "!!!"):
            with self.subTest(text=text):
                self.assertEqual(comparison_text(text), "")

    def test_the_article_rule_is_not_a_name_rule(self):
        """§3.1 step 6 is titles only: an author named `A. Smith` is not an article."""
        self.assertEqual(comparison_text("A. Smith"), "a smith")


class SimilarityTests(unittest.TestCase):
    """§3.2's calibration, against the anchors and the measured rows of its table.

    Most of these read the title's similarity back off a score. With the author
    absent from the denominator (§1.3) the score is
    `min(title_similarity, NO_AGREEMENT_CEILING)`, so a similarity at or under
    the 0.7 cap - which every anchor below is - comes back unchanged.
    """

    def title_similarity(self, file_title, candidate_title):
        match = score_candidate(
            FileBook(file_title, ()), candidate(title=candidate_title, authors=())
        )

        self.assertFalse(match.author_agrees, "the fixture is title-only on purpose")
        self.assertEqual(match.denominator, TITLE_ALONE)
        return match.title_similarity

    def test_identical_input_is_exactly_one(self):
        """§1.1: a perfect match must be exactly 1.0, not 0.997."""
        self.assertEqual(self.title_similarity(BARE, BARE), 1.0)
        self.assertEqual(self.title_similarity("Cragside!", BARE), 1.0)

    def test_the_measured_rows_of_the_similarity_table(self):
        """§2.1's title similarities, each with the raw ratio that table prints.

        These four are the design's own computed numbers rather than shapes: an
        interpolation that is off by a segment still lands near 1.0 and near
        0.0, and only these catch it.
        """
        table = (
            # the file's title, the record's, §2.1's row, its raw, its similarity
            (MESSY, "Cragside", "row 1", 1.0, 1.0),
            (MESSY, "Cragside: A DCI Ryan Mystery", "row 5", 1.0, 1.0),
            (MESSY, "Cragside: A 1930s murder mystery", "row 11", 0.7241, 0.4134),
            (MESSY, "The Infirmary", "row 8", 0.1905, 0.0),
        )
        for file_title, candidate_title, row, raw, expected in table:
            with self.subTest(row=row):
                self.assertEqual(
                    self.title_similarity(file_title, candidate_title),
                    round(1.0 - penalty(raw), 4),
                )
                self.assertAlmostEqual(
                    self.title_similarity(file_title, candidate_title),
                    expected,
                    places=4,
                )

    def test_the_dead_band_makes_a_near_identical_ratio_cost_nothing(self):
        """§3.2's dead band at 0.97, and the first segment above it.

        `a` × 33 against `a` × 32 is a ratio of exactly 0.984615, which §3.2's
        table reads as 0.22 × (1 - 0.15385) = 0.1862 of penalty at 0.90.
        """
        self.assertAlmostEqual(
            self.title_similarity("a" * 33, "a" * 32),
            round(1.0 - penalty(0.984615), 4),
        )

    def test_the_anchor_where_the_table_says_the_penalty_is_nothing(self):
        """§3.2's table: ratio 1.00 is penalty 0.00."""
        self.assertEqual(penalty(1.00), 0.0)

    def test_the_floor_makes_a_wholly_different_title_a_clean_one(self):
        """§3.2: below ratio 0.35 the penalty is a clean 1, not 0.65."""
        for raw in (0.0, 0.19, 0.34):
            with self.subTest(raw=raw):
                self.assertEqual(penalty(raw), 1.0)
        self.assertEqual(penalty(0.35), 1.00)
        self.assertEqual(self.title_similarity("ab", "z"), 0.0)

    def test_the_curve_is_the_table_at_every_anchor(self):
        """§3.2's whole table, read as penalty for a given raw ratio."""
        for raw, expected in STRETCH:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(penalty(raw), expected, places=4)


class TitleComparisonTests(unittest.TestCase):
    """§3.3's one form per side, and which stage each case takes."""

    def title_similarity(self, file_title, candidate_title):
        return score_candidate(
            FileBook(file_title, LJ),
            candidate(title=candidate_title, authors=("M.J. Porter",)),
        ).title_similarity

    def test_both_sides_subtitling_compares_the_full_titles(self):
        """§3.3's table: `Cragside: A 1930s murder mystery` is 0.4134, not 1.0.

        The two heads are one word; the subtitles are what tell them apart, and
        max-over-forms would have scored this at 1.0000.
        """
        self.assertAlmostEqual(
            self.title_similarity(MESSY, "Cragside: A 1930s murder mystery"),
            0.4134,
            places=4,
        )

    def test_one_side_bare_compares_the_heads(self):
        """§3.3's table: a record that keeps a subtitle the file dropped costs
        nothing - `Cragside` against the messy file's title is 1.0000."""
        self.assertEqual(self.title_similarity(MESSY, "Cragside"), 1.0)

    def test_one_side_bare_is_symmetric(self):
        """The same rule from the file's side: the bare file against the full record."""
        self.assertEqual(
            self.title_similarity(BARE, "Cragside: A DCI Ryan Mystery"), 1.0
        )

    def test_the_title_is_silent_when_both_sides_carry_the_same_subtitle(self):
        """§3.3: row 7's Porter record scores 1.0000 on the title, and only the
        author gate refuses it. The title is not a second opinion there."""
        self.assertEqual(
            self.title_similarity(MESSY, "Cragside: A DCI Ryan Mystery"), 1.0
        )

    def test_the_bracket_comes_off_the_raw_title_before_the_split(self):
        """§3.3: the split has to happen before normalisation destroys the colon.

        The messy title's scored form is its head and subtitle with the bracket
        removed, so a record with a different subtitle is 0.4134 against it.
        """
        self.assertAlmostEqual(
            self.title_similarity(MESSY, "Cragside: A 1930s murder mystery"),
            round(1.0 - penalty(0.7241), 4),
        )

    def test_a_record_whose_subtitle_differs_is_refused_even_though_the_head_agrees(
        self,
    ):
        """§3.3: the case max-over-forms got wrong, stated as a verdict."""
        match = score_candidate(
            FileBook("Cragside: A DCI Ryan Mystery", LJ),
            candidate(
                title="Cragside: A 1930s murder mystery",
                authors=("L.J. Ross",),
                date="2017-07-07",
            ),
        )

        self.assertLess(match.score, 0.89, "§4.1's multi-candidate strong bar")
        self.assertTrue(match.author_agrees)


class AuthorComparisonTests(unittest.TestCase):
    """§3.4's ordering, its gate and its per-creator calibration."""

    def author_match(self, file_authors, record_authors):
        return score_candidate(
            FileBook(BARE, file_authors), candidate(title=BARE, authors=record_authors)
        )

    def test_the_measured_pairs_in_the_name_table(self):
        """§3.4's table: the shipped `_name` verdict, the raw ratio and the
        calibrated similarity, in the order that table gives them.

        The expected values are the table's own, to four places. Where the
        table prints a raw ratio rounded to four places (0.8571), the penalty
        is computed here from the rounded figure, so a similarity within a
        thousandth of the printed one is what this asserts.
        """
        table = (
            # file author, record author, §3.4's raw, §3.4's similarity, agrees
            ("L. J. Ross", "L. J. Ros", 0.9231, 0.8308, True),
            ("L. J. Ross", "L. J. Riss", 0.8571, 0.6814, True),
            ("LJ Ross", "Ross LJ", 0.5714, 0.1914, False),
            ("Ross, L. J.", "L. J. Ross", 1.0, 1.0, True),
            ("L.J. Ross", "L. J. Ross", 1.0, 1.0, True),
        )
        for file_author, record_author, raw, expected, agrees in table:
            with self.subTest(file=file_author, record=record_author):
                match = self.author_match((file_author,), (record_author,))

                self.assertAlmostEqual(
                    match.author_similarity, round(1.0 - penalty(raw), 4), places=3
                )
                self.assertAlmostEqual(match.author_similarity, expected, places=3)
                self.assertEqual(match.author_agrees, agrees)

    def test_the_floor_s_own_worked_list(self):
        """§1.3's list of what 0.5 admits and what it refuses, as calibrated
        similarities read out of §3.4's curve.

        `Ursula Le Guin` at 0.8533 is the note's own pairing of `Ursula K. Le
        Guin` against `Ursula Le Guin` - the surname with an initial dropped,
        which is the variant the floor is there to admit. A whole surname
        against `L. J. Ross` is not that case: it is below §3.2's 0.35 floor and
        scores a clean 0.0000.
        """
        agrees = (
            ("L.J. Ross", 1.0000),
            ("LJ Ross", 1.0000),
            ("Ross, L. J.", 1.0000),
            ("L. J. Riss", 0.6814),
            ("L. K. Ross", 0.6814),
        )
        refuses = (
            ("M.J. Porter", 0.0200),
            ("Carly Reagon", 0.0568),
            ("M. J. Ross-Smith", 0.2200),
            ("Ross, Carly", 0.3806),
            ("L. J. Roth", 0.3957),
            ("John Ross", 0.4600),
        )
        for record_author, expected in agrees:
            with self.subTest(record=record_author, agrees=True):
                match = self.author_match(LJ, (record_author,))

                self.assertAlmostEqual(match.author_similarity, expected, places=3)
                self.assertTrue(match.author_agrees)
                self.assertGreaterEqual(match.author_similarity, AUTHOR_AGREES)
        for record_author, expected in refuses:
            with self.subTest(record=record_author, agrees=False):
                match = self.author_match(LJ, (record_author,))

                self.assertAlmostEqual(match.author_similarity, expected, places=3)
                self.assertFalse(match.author_agrees)
                self.assertLess(match.author_similarity, AUTHOR_AGREES)

    def test_a_dropped_initial_is_the_variant_the_floor_admits(self):
        """§1.3's `Ursula Le Guin` at 0.8533, against the name it is short for."""
        match = self.author_match(("Ursula K. Le Guin",), ("Ursula Le Guin",))

        self.assertAlmostEqual(match.author_similarity, 0.8533, places=3)
        self.assertTrue(match.author_agrees)

    def test_a_whole_different_surname_is_below_the_floor(self):
        """The other half of the same list: `L. J. Ross` against `Ursula Le Guin`
        shares no surname, and §3.2's floor makes it a clean 0.0000."""
        match = self.author_match(LJ, ("Ursula Le Guin",))

        self.assertEqual(match.author_similarity, 0.0)
        self.assertFalse(match.author_agrees)

    def test_the_floor_is_half_and_is_where_the_design_puts_it(self):
        """§1.3: `AUTHOR_AGREES = 0.5`, a property of the metric rather than a
        preference - so it is not a config key."""
        self.assertEqual(AUTHOR_AGREES, 0.5)

    def test_a_surname_first_name_is_reversed_before_it_is_compared(self):
        """§3.4 step 1: the comma form is turned round, so it scores 1.0."""
        self.assertAlmostEqual(
            self.author_match(("L. J. Ross",), ("Ross, L. J.",)).author_similarity,
            1.0,
            places=4,
        )

    def test_initials_are_joined_before_the_similarity_sees_them(self):
        """§3.4 step 2: `J. R. R.` joins to `jrr` and agrees with `JRR`."""
        for record_author in ("J.R.R. Tolkien", "J. R. R. Tolkien", "JRR Tolkien"):
            with self.subTest(record=record_author):
                match = self.author_match(("JRR Tolkien",), (record_author,))

                self.assertAlmostEqual(match.author_similarity, 1.0, places=4)

    def test_ursula_le_guin_does_not_become_one_token(self):
        """§3.4 step 2 keeps `Ursula K. Le Guin` from joining across the word gap."""
        self.assertEqual(normalise("Ursula K. Le Guin"), "ursula k le guin")
        joined = self.author_match(("Ursula K. Le Guin",), ("UrsulaKLeGuin",))
        written = self.author_match(("Ursula K. Le Guin",), ("Ursula K. Le Guin",))

        self.assertAlmostEqual(written.author_similarity, 1.0, places=4)
        self.assertLess(joined.author_similarity, written.author_similarity)

    def test_each_creator_is_calibrated_and_the_calibrated_values_averaged(self):
        """§3.4: each file creator takes its **best** match, then those average.

        The file names `L. J. Ross` twice and the record names `L. K. Ross` and
        `L. J. Ross`. Each of the file's two creators scores 0.6814 against one
        record author and 1.0000 against the other, so each contributes its
        maximum, 1.0000, and the field is their average: 1.0000.

        The two orderings §3.4 forbids both give something else. Averaging
        across the *record's* authors first — the cartesian mean — is
        (0.6814 + 1.0 + 0.6814 + 1.0)/4 = 0.8407, and calibrating the average of
        the raw ratios is 0.8429.
        """
        match = self.author_match(
            ("L. J. Ross", "L. J. Ross"), ("L. K. Ross", "L. J. Ross")
        )

        self.assertAlmostEqual(match.author_similarity, (1.0 + 1.0) / 2, places=4)
        self.assertNotAlmostEqual(match.author_similarity, 0.8407, places=4)
        self.assertNotAlmostEqual(match.author_similarity, 0.8429, places=4)
        self.assertTrue(match.author_agrees)

    def test_one_creator_against_two_record_authors_takes_the_best(self):
        """§3.4: a record listing a second name the file omits costs nothing.

        `L. J. Ross` against `L. J. Ross` is 1.0000 and against `M.J. Porter`
        0.0200 (§1.3's list). The file names one creator, so the field is that
        creator's best match: 1.0000, and the gate passes. The cartesian mean
        would be (1.0000 + 0.0200)/2 = 0.5100, which sits barely over the floor
        and would fall under it for any second name scoring worse than 0.
        """
        match = self.author_match(LJ, ("L. J. Ross", "M.J. Porter"))

        self.assertAlmostEqual(match.author_similarity, 1.0000, places=4)
        self.assertTrue(match.author_agrees)

    def test_one_creator_against_three_record_authors_takes_the_best(self):
        """§3.4: three record authors — a co-author, a translator, an illustrator.

        The same creator against `L. J. Ross` 1.0000, `M.J. Porter` 0.0200 and
        `Carly Reagon` 0.0568. The best is 1.0000, so the gate passes; the
        cartesian mean would be (1.0000 + 0.0200 + 0.0568)/3 = 0.3589, under the
        0.5 floor, which is the failure §3.4 exists to prevent.
        """
        match = self.author_match(LJ, ("L. J. Ross", "M.J. Porter", "Carly Reagon"))

        self.assertAlmostEqual(match.author_similarity, 1.0000, places=4)
        self.assertTrue(match.author_agrees)

    def test_two_creators_each_take_their_own_best_and_the_two_average(self):
        """§3.4's arithmetic, spelled out when the maxima come from one record author.

        The file names `L. J. Ross` and `Carly Reagon`; the record names
        `L. K. Ross` and `Carly Reagon`.

        * `L. J. Ross`'s best against the record is 0.6814 — against `L. K. Ross`,
          since against `Carly Reagon` it is 0.0568.
        * `Carly Reagon`'s best is 1.0000, against the record's own `Carly Reagon`.

        The per-creator maxima are 0.6814 and 1.0000, so the field is
        (0.6814 + 1.0000)/2 = 0.8407 and the gate passes. It is the same number
        the cartesian mean gives here — each creator's maximum happens to come
        from a different record author — which is exactly why the cartesian mean
        is not detectable from a mix of one-to-one pairs and needed the
        one-creator cases above.
        """
        match = self.author_match(
            ("L. J. Ross", "Carly Reagon"), ("L. K. Ross", "Carly Reagon")
        )

        self.assertAlmostEqual(match.author_similarity, (0.6814 + 1.0000) / 2, places=4)
        self.assertAlmostEqual(match.author_similarity, 0.8407, places=4)
        self.assertTrue(match.author_agrees)

    def test_one_creator_against_two_record_authors_with_no_match_fails(self):
        """§3.4 with §1.3's floor: no record author reaches it, so the gate fails.

        `L. J. Ross` scores 0.0200 against `M.J. Porter` and 0.0568 against
        `Carly Reagon`, so the best is 0.0568 — a single comparison either way,
        since the file names one creator — and 0.0568 is under 0.5.
        """
        match = self.author_match(LJ, ("M.J. Porter", "Carly Reagon"))

        self.assertAlmostEqual(match.author_similarity, 0.0568, places=4)
        self.assertFalse(match.author_agrees)

    def test_a_file_that_names_no_creator_never_agrees(self):
        """§1.3: the file must name at least one creator."""
        match = self.author_match((), ("L. J. Ross",))

        self.assertFalse(match.author_agrees)
        self.assertIsNone(match.author_similarity)

    def test_a_record_that_names_no_creator_never_agrees(self):
        """§1.3: and the record must name one too."""
        match = self.author_match(("L. J. Ross",), ())

        self.assertFalse(match.author_agrees)
        self.assertIsNone(match.author_similarity)

    def test_a_matching_author_with_a_different_title_does_not_agree(self):
        """§1.3's gate passes and the candidate is still not an explanation.

        `The Infirmary` has nothing in common with the file's title, so
        `title_similarity` is 0.0 and `agrees` is false even though the author
        reaches the floor. That is the verdict a near-miss log line reads, and
        it is what stops an unrelated book of the same author being named as the
        closest thing to this one.
        """
        match = score_candidate(
            FileBook(BARE, LJ), candidate(title="The Infirmary", authors=LJ)
        )

        self.assertEqual(match.title_similarity, 0.0)
        self.assertTrue(match.author_agrees)
        self.assertFalse(match.agrees)
        self.assertGreater(match.score, 0.0, "the author still scores")


class ScoreTests(unittest.TestCase):
    """§2's accumulator, against §2.1's rows and §2.2's regression table."""

    def test_row_1_every_field_that_can_agree_does(self):
        """§2.1 row 1: title, author, series and year all agree, over 2.15.

        Every penalty is 0, so the score is 1.0 exactly - which is §1.1's
        requirement on the accumulation rather than a rounding accident.
        """
        match = score_candidate(FileBook(MESSY, LJ, date="2017-07-07"), CRAGSIDE_RECORD)

        self.assertEqual(match.score, 1.0)
        self.assertEqual(match.denominator, ALL_FOUR)
        self.assertTrue(match.author_agrees)

    def test_row_2_the_file_has_no_year_so_the_year_is_not_compared(self):
        """§2.1 row 2: the year is absent from the file, so 2.00 is the scale."""
        match = score_candidate(FileBook(MESSY, LJ), CRAGSIDE_RECORD)

        self.assertEqual(match.score, 1.0)
        self.assertEqual(match.denominator, NO_YEAR)

    def test_row_3_the_series_and_the_year_both_contradict(self):
        """§2.1 row 3: 1 − (0.20 + 0.15)/2.15 = 0.8372, medium."""
        match = score_candidate(
            FileBook(MESSY, LJ, date="2017-07-07"),
            candidate(title="Cragside", series_number="11", date="1999-01-01"),
        )

        self.assertAlmostEqual(
            match.score, 1.0 - (SERIES_W + YEAR_W) / ALL_FOUR, places=4
        )
        self.assertAlmostEqual(match.score, 0.8372, places=4)
        self.assertEqual(match.denominator, ALL_FOUR)

    def test_row_4_the_series_contradicts_and_nothing_else(self):
        """§2.1 row 4: 1 − 0.20/2.15 = 0.9070, medium for a singleton."""
        match = score_candidate(
            FileBook(MESSY, LJ, date="2017-07-07"),
            candidate(title="Cragside", series_number="11", date="2017-07-07"),
        )

        self.assertAlmostEqual(match.score, 1.0 - SERIES_W / ALL_FOUR, places=4)
        self.assertAlmostEqual(match.score, 0.9070, places=4)

    def test_row_5_the_record_keeps_the_subtitle(self):
        """§2.1 row 5: identical full titles, 0.9070 on the series disagreement."""
        match = score_candidate(
            FileBook(MESSY, LJ, date="2017-07-07"),
            candidate(
                title="Cragside: A DCI Ryan Mystery",
                series_number="11",
                date="2017-07-07",
            ),
        )

        self.assertEqual(match.title_similarity, 1.0)
        self.assertAlmostEqual(match.score, 0.9070, places=4)

    def test_row_7_the_subtitle_agrees_and_only_the_author_refuses_it(self):
        """§2.1 row 7: an exact title, 1.00 left in the denominator, capped at 0.7."""
        match = score_candidate(
            FileBook(MESSY, LJ),
            candidate(title="Cragside: A DCI Ryan Mystery", authors=("M.J. Porter",)),
        )

        self.assertEqual(match.denominator, TITLE_ALONE)
        self.assertAlmostEqual(match.author_similarity, 0.0200, places=4)
        self.assertEqual(match.score, NO_AGREEMENT_CEILING)
        self.assertFalse(match.author_agrees)

    def test_row_8_a_different_book_by_the_same_author(self):
        """§2.1 row 8: title 0.0000, author 1.0000 -> 0.4444 at 1.80.

        The note prints 1.80 for this row, which is title and author with no
        series. Its candidate carries a series position the file's title also
        states, so §2's two-sided rule puts series in the denominator: the scale
        is 2.00 and the score 1 - (1.00 + 0.20)/2.00 = 0.4. 1.80 needs the
        candidate's position to be absent, which is the second assertion, and
        the score there is the note's 0.4444. Both facts are recorded in
        `pr-cbo-58.md` rather than papered over.
        """
        match = score_candidate(
            FileBook(MESSY, LJ),
            candidate(title="The Infirmary", authors=LJ, series_number="11"),
        )

        self.assertEqual(match.denominator, NO_YEAR)
        # §3.2's floor makes this row's title a clean penalty of 1 - its raw
        # ratio of 0.1905 is below 0.35 - and the series position disagrees, so
        # the score is 1 - (1.00 + 0.20)/2.00 = 0.4 on this scale.
        self.assertEqual(match.title_similarity, 0.0)
        self.assertAlmostEqual(
            match.score, 1.0 - (TITLE_W + SERIES_W) / NO_YEAR, places=4
        )
        without_a_position = score_candidate(
            FileBook(MESSY, LJ),
            candidate(title="The Infirmary", authors=LJ),
        )
        self.assertEqual(without_a_position.denominator, TITLE_AUTHOR)
        self.assertAlmostEqual(without_a_position.score, 0.4444, places=4)

    def test_row_9_a_different_book_by_a_different_author(self):
        """§2.1 row 9: neither agrees, 1.00 -> 0.0000."""
        match = score_candidate(
            FileBook(MESSY, LJ),
            candidate(title="The Infirmary", authors=("Carly Reagon",)),
        )

        self.assertEqual(match.denominator, TITLE_ALONE)
        self.assertEqual(match.score, 0.0)
        self.assertFalse(match.author_agrees)

    def test_row_10_the_gate_holds_a_file_that_names_no_author(self):
        """§2.1 row 10: three fields compare and score 1.0000 without the gate;
        the gate holds it at 0.7000 on the 1.35 scale."""
        match = score_candidate(FileBook(MESSY, (), date="2017-07-07"), CRAGSIDE_RECORD)

        self.assertEqual(match.denominator, TITLE_SERIES_YEAR)
        self.assertEqual(match.score, NO_AGREEMENT_CEILING)
        self.assertFalse(match.author_agrees)

    def test_row_11_the_subtitles_differ_so_the_title_carries_the_evidence(self):
        """§2.1 row 11: 0.4134 of title similarity, alone on the 1.00 scale."""
        match = score_candidate(
            FileBook(MESSY, LJ),
            candidate(
                title="Cragside: A 1930s murder mystery", authors=("M.J. Porter",)
            ),
        )

        self.assertEqual(match.denominator, TITLE_ALONE)
        self.assertAlmostEqual(match.score, 0.4134, places=4)

    def test_an_agreeing_author_keeps_its_weight_in_the_denominator(self):
        """§1.3: 0.80 leaves the denominator only when the gate fails."""
        agreeing = score_candidate(
            FileBook(MESSY, LJ), candidate(title="Cragside", authors=("L.J. Ross",))
        )
        refusing = score_candidate(
            FileBook(MESSY, LJ), candidate(title="Cragside", authors=("M.J. Porter",))
        )

        self.assertEqual(agreeing.denominator, TITLE_AUTHOR)
        self.assertEqual(refusing.denominator, TITLE_ALONE)

    def test_the_cap_is_the_shipped_ceiling(self):
        """§1.3: `NO_AGREEMENT_CEILING = 0.7`, kept at the shipped value so the
        number in the log stays comparable with what the pipeline logs today."""
        self.assertEqual(NO_AGREEMENT_CEILING, 0.7)

    def test_isbn_is_never_scored_however_it_disagrees(self):
        """§2: ISBN weighs 0.00, and a conflicting one is not a penalty either."""
        with_one = score_candidate(
            FileBook(MESSY, LJ), candidate(title="Cragside", isbn="9781521748831")
        )
        contradicting = score_candidate(
            FileBook(MESSY, LJ), candidate(title="Cragside", isbn="9780000000000")
        )

        self.assertEqual(with_one.score, contradicting.score)
        self.assertEqual(contradicting.denominator, TITLE_AUTHOR)

    def test_publisher_is_not_a_field_at_all(self):
        """§2: publisher is dropped, and is not on `FileBook` either."""
        self.assertNotIn("publisher", FileBook.__dataclass_fields__)

    def test_a_date_that_is_not_a_four_digit_year_is_not_compared(self):
        """§2: the year is compared when both sides carry a four-digit year."""
        match = score_candidate(
            FileBook(MESSY, LJ, date="2017-07-07"),
            candidate(title="Cragside", series_number="6", date="fall 1999"),
        )

        self.assertEqual(match.denominator, NO_YEAR)


class BandTests(unittest.TestCase):
    """§4.1's bands, at every denominator the design produces.

    The sweep below is §4.1's arithmetic written out: a leader whose title
    similarity is `1 - penalty(raw)` at denominator `d` scores
    `1 - penalty(raw)/d`, and the band follows from `strong_score`,
    `singleton_score`, `medium_score` and the gap. The `raw` values are §3.2's
    anchors and the pairs beside them produce those ratios exactly, so every
    expected score here is checkable by hand.
    """

    def test_a_singleton_is_strong_only_at_the_singleton_bar(self):
        """§4.1: one candidate needs `score ≥ 0.95`, and §4.1 gives the table.

        The file's series and year both disagree, so on the full scale
        `score = 1 − (title penalty + 0.35)/2.15`. The exact title scores 0.8372
        and is medium; a head one word shorter scores 0.7519 and is low. §4.1's
        singleton bar of 0.95 refuses both, which is the same reason §2.1's rows
        4 and 5 are medium.
        """
        file_book = FileBook("a a a a a a a a (Book 6)", LJ, date="2017-07-07")
        cases = (
            # the record's head, its title similarity, §4.1's verdict
            ("a a a a a a a a", 1.0000, "medium"),
            ("a a a a a a a", 0.8167, "low"),
            ("a a a a a a", 0.5918, "low"),
        )
        for title, similarity, expected in cases:
            with self.subTest(title=title):
                record = candidate(title=title, series_number="11", date="1999-01-01")
                ranked = rank(file_book, [record])

                self.assertEqual(ranked.matches[0].denominator, ALL_FOUR)
                self.assertAlmostEqual(
                    ranked.matches[0].title_similarity, similarity, places=4
                )
                self.assertAlmostEqual(
                    ranked.matches[0].score,
                    round(1.0 - ((1.0 - similarity) + SERIES_W + YEAR_W) / ALL_FOUR, 4),
                    places=3,
                )
                self.assertLess(ranked.matches[0].score, 0.95)
                self.assertEqual(band_of(ranked), expected)

    def test_a_singleton_with_an_exact_title_is_strong_at_the_bar(self):
        """§2.1 row 1: nothing contradicts, so the singleton bar is cleared.

        The same record as the test above with every field agreeing: 1.0000 at
        2.15, which is over `singleton_score` and over `strong_score` both.
        """
        ranked = rank(FileBook(MESSY, LJ, date="2017-07-07"), [CRAGSIDE_RECORD])

        self.assertEqual(ranked.matches[0].score, 1.0)
        self.assertEqual(band_of(ranked), "strong")

    def test_the_singleton_bar_across_the_denominators(self):
        """§4.1 and §2: the same wrong evidence grades differently on each scale.

        The title is 0.8167 similar (a head one word shorter) and every other
        field the fixture supplies disagrees. A year alone puts 1.15 in the
        denominator with no author to agree, so the gate caps it at 0.7 - low; a
        series and a year 1.35 and 0.6049 - low; an author and a year 1.95 and
        0.8291 - medium; and with a series too 2.15 and 0.7519 - low again.
        §4.1's singleton bar of 0.95 refuses all five.
        """
        cases = (
            # the file, the record, the denominator, the score, the band
            (
                FileBook("a a a a a a a a", (), date="2017-07-07"),
                candidate(title="a a a a a a a", authors=(), date="1999-01-01"),
                1.15,
                0.7000,
                "low",
            ),
            (
                FileBook("a a a a a a a a (Book 6)", (), date="2017-07-07"),
                candidate(
                    title="a a a a a a a",
                    authors=(),
                    series_number="11",
                    date="1999-01-01",
                ),
                TITLE_SERIES_YEAR,
                0.6049,
                "low",
            ),
            (
                FileBook("a a a a a a a a", LJ, date="2017-07-07"),
                candidate(
                    title="a a a a a a a",
                    authors=("M.J. Porter",),
                    date="1999-01-01",
                ),
                1.15,
                0.7000,
                "low",
            ),
            (
                FileBook("a a a a a a a a", LJ, date="2017-07-07"),
                candidate(title="a a a a a a a", authors=LJ, date="1999-01-01"),
                TITLE_AUTHOR + YEAR_W,
                0.8291,
                "medium",
            ),
            (
                FileBook("a a a a a a a a (Book 6)", LJ, date="2017-07-07"),
                candidate(
                    title="a a a a a a a",
                    authors=LJ,
                    series_number="11",
                    date="1999-01-01",
                ),
                ALL_FOUR,
                0.7519,
                "low",
            ),
        )
        for file_book, record, denominator, expected_score, expected in cases:
            with self.subTest(denominator=denominator, score=expected_score):
                ranked = rank(file_book, [record])

                self.assertEqual(ranked.matches[0].denominator, denominator)
                self.assertAlmostEqual(
                    ranked.matches[0].title_similarity, 0.8167, places=3
                )
                self.assertAlmostEqual(
                    ranked.matches[0].score, expected_score, places=3
                )
                self.assertLess(ranked.matches[0].score, 0.95)
                self.assertEqual(band_of(ranked), expected)

    def test_a_wrong_author_is_never_strong_however_high_it_scores(self):
        """§6 item 3 and §4.1: 0.8584 is a wrong author clearing the 0.5 gate.

        §4.1's window is (0.8584, 0.9070] and a singleton refuses it at 0.95.
        The margin at 2.15 is thinner - the same author scores 0.8814 there -
        and §4.1 refuses that too. This implementation prints 0.8815 at 2.15,
        one ten-thousandth above the note: it applies §3.2's segment to the
        **unrounded** similarity, where §6 item 3's 0.8814 comes from applying
        that segment to the ratio as the note's own table prints it, 0.8571.
        The difference is recorded in `pr-cbo-58.md` under "Expected values I
        changed", and the score is asserted at three places for that reason.
        """
        file_book = FileBook(MESSY, LJ, date="2017-07-07")
        cases = (
            # the record, the file it is scored against, the denominator, the score
            (
                candidate(title=BARE, authors=("L. K. Ross",)),
                FileBook(BARE, LJ, date="2017-07-07"),
                TITLE_AUTHOR,
                0.8584,
            ),
            (
                candidate(
                    title=BARE,
                    authors=("L. K. Ross",),
                    series_number="6",
                    date="2017-07-07",
                ),
                file_book,
                ALL_FOUR,
                0.8815,
            ),
        )
        for record, against, denominator, expected in cases:
            with self.subTest(score=expected):
                ranked = rank(against, [record])

                self.assertEqual(ranked.matches[0].denominator, denominator)
                self.assertAlmostEqual(ranked.matches[0].score, expected, places=3)
                self.assertTrue(ranked.matches[0].author_agrees)
                self.assertEqual(band_of(ranked), "medium")
                self.assertLess(ranked.matches[0].score, 0.95)
                self.assertGreater(ranked.matches[0].score, 0.80)

    def test_the_multi_candidate_bar_and_the_gap_at_every_reachable_denominator(self):
        """§4.1: two or more, `score ≥ 0.89` **and** `gap ≥ 0.08`.

        Each pool's leader is perfect and its runner-up disagrees about one
        field, so the gap is that field's §2 weight over the scale the two
        records produce: at 1.35 the series gives 0.20/2.00 = 0.1000, at 1.80
        the author's 0.80/1.80 = 0.4444, and at 2.15 the series again
        0.20/2.15 = 0.0930. All three clear 0.08 and grade strong.
        """
        cases = (
            # file, leader, runner-up, the leader's denominator, the gap
            (
                FileBook("Cragside (Book 6)", LJ),
                candidate(title=BARE, authors=LJ, series_number="6"),
                candidate(title=BARE, authors=LJ, series_number="11"),
                2.00,
                0.1000,
            ),
            (
                FileBook(BARE, LJ),
                candidate(title=BARE, authors=LJ),
                candidate(title=BARE, authors=("M.J. Porter",)),
                TITLE_AUTHOR,
                0.3000,
            ),
            (
                FileBook(MESSY, LJ, date="2017-07-07"),
                CRAGSIDE_RECORD,
                candidate(
                    title=BARE, authors=LJ, series_number="11", date="2017-07-07"
                ),
                ALL_FOUR,
                0.0930,
            ),
        )
        for file_book, leader, runner_up, denominator, gap in cases:
            with self.subTest(denominator=denominator):
                ranked = rank(file_book, [leader, runner_up])

                self.assertEqual(ranked.matches[0].denominator, denominator)
                self.assertEqual(ranked.matches[0].score, 1.0)
                self.assertAlmostEqual(ranked.gap, gap, places=4)
                self.assertGreaterEqual(ranked.gap, 0.08)
                self.assertGreaterEqual(ranked.matches[0].score, 0.89)
                self.assertEqual(band_of(ranked), "strong")

    def test_a_leader_that_clears_the_score_but_not_the_gap_is_medium(self):
        """§4.1: the gap is a second, independent bar.

        At 1.95 a perfect leader against a runner-up whose year disagrees scores
        1.0000 with a gap of 0.15/1.95 = 0.0769 - under 0.08 - so the pool is
        medium however high the leader's own number is. That is §1.2's whole
        argument: a high score with no separation is not a decision.
        """
        file_book = FileBook(BARE, LJ, date="2017-07-07")
        ranked = rank(
            file_book,
            [
                candidate(title=BARE, date="2017-07-07"),
                candidate(title=BARE, date="1999-01-01"),
            ],
        )

        self.assertEqual(ranked.matches[0].denominator, NO_YEAR - 0.05)
        self.assertEqual(ranked.matches[0].score, 1.0)
        self.assertAlmostEqual(ranked.gap, 0.0769, places=4)
        self.assertLess(ranked.gap, 0.08)
        self.assertEqual(band_of(ranked), "medium")

    def test_a_leader_that_clears_the_score_but_not_the_gap_is_medium_at_215(self):
        """The same bar at the full scale: 0.15/2.15 = 0.0698, also under 0.08."""
        ranked = rank(
            FileBook(MESSY, LJ, date="2017-07-07"),
            [
                CRAGSIDE_RECORD,
                candidate(title=BARE, series_number="6", date="1999-01-01"),
            ],
        )

        self.assertEqual(ranked.matches[0].denominator, ALL_FOUR)
        self.assertEqual(ranked.matches[0].score, 1.0)
        self.assertAlmostEqual(ranked.gap, 0.0698, places=4)
        self.assertLess(ranked.gap, 0.08)
        self.assertEqual(band_of(ranked), "medium")

    def test_a_title_similarity_sweep_at_every_denominator(self):
        """§4.1's bar against §3.2's curve, at all four denominators.

        The file's head and the record's are runs of the same word, so the
        ratio is exact: `a` eight times against `a` seven times is 0.916667,
        which §3.2 reads as 0.1833 of penalty and 0.8167 of similarity. Each
        row's score is `1 - (0.1833 + the fields that disagree)/d`, and the
        fixture is spelled out per row so the denominator it claims is the one
        the fields produce.
        """
        cases = (
            # the file, the record, the denominator, §4.1's verdict
            (
                FileBook("a a a a a a a a"),
                candidate(title="a a a a a a a", authors=LJ),
                TITLE_ALONE,
                0.7000,
                "low",
            ),
            (
                FileBook("a a a a a a a a (Book 6)", LJ),
                candidate(title="a a a a a a a", authors=LJ, series_number="6"),
                2.00,
                0.9083,
                "medium",
            ),
            (
                FileBook("a a a a a a a a", LJ),
                candidate(title="a a a a a a a", authors=("M.J. Porter",)),
                TITLE_ALONE,
                0.7000,
                "low",
            ),
            (
                FileBook("a a a a a a a a (Book 6)", LJ, date="2017-07-07"),
                candidate(
                    title="a a a a a a a",
                    authors=LJ,
                    series_number="11",
                    date="1999-01-01",
                ),
                ALL_FOUR,
                0.7519,
                "low",
            ),
        )
        for file_book, record, denominator, expected_score, expected in cases:
            with self.subTest(denominator=denominator, score=expected_score):
                ranked = rank(file_book, [record])

                self.assertEqual(ranked.matches[0].denominator, denominator)
                self.assertAlmostEqual(
                    ranked.matches[0].title_similarity, 0.8167, places=3
                )
                self.assertAlmostEqual(
                    ranked.matches[0].score, expected_score, places=3
                )
                self.assertEqual(band_of(ranked), expected)

    def test_the_title_similarity_sweep_walks_a_pool_through_the_reachable_bands(self):
        """§4.1's bands against §3.2's curve, at one denominator.

        The record's head is a shorter run of the same word each time, so the
        title similarity falls away continuously rather than flipping between
        the binary series and year cases - the sweep HARD RULE 3 asks for. The
        file's series and year both disagree, so the score is
        `1 - (title penalty + 0.35)/2.15` and the author still agrees. The
        first row is `medium` because 0.8372 is under 0.95, which is the same
        reason §2.1's rows 4 and 5 are medium.
        """
        cases = (
            # the record's head, the title similarity, the band §4.1 gives it
            ("a a a a a a a a", 1.0000, "medium"),
            ("a a a a a a a", 0.8167, "low"),
            ("a a a a a a", 0.5918, "low"),
            ("a a a", 0.0200, "low"),
        )
        for record_head, similarity, expected in cases:
            with self.subTest(head=record_head):
                file_book = FileBook("a a a a a a a a (Book 6)", LJ, date="2017-07-07")
                record = candidate(
                    title=record_head, series_number="11", date="1999-01-01"
                )
                ranked = rank(file_book, [record])

                self.assertAlmostEqual(
                    ranked.matches[0].title_similarity, similarity, places=4
                )
                self.assertAlmostEqual(
                    ranked.matches[0].score,
                    round(1.0 - ((1.0 - similarity) + SERIES_W + YEAR_W) / ALL_FOUR, 4),
                    places=3,
                )
                self.assertEqual(band_of(ranked), expected)

    def test_a_title_below_the_floor_is_a_clean_zero_and_the_none_band(self):
        """§3.2's floor and §4.1's `none`.

        A wholly different title is a penalty of 1, not 0.65, so on a scale that
        is the title alone the score is exactly 0.0 - which §4.1 bands as `none`
        rather than `low`.
        """
        ranked = rank(
            FileBook(BARE, ()), [candidate(title="The Infirmary", authors=())]
        )

        self.assertEqual(ranked.matches[0].title_similarity, 0.0)
        self.assertEqual(ranked.matches[0].denominator, TITLE_ALONE)
        self.assertEqual(ranked.matches[0].score, 0.0)
        self.assertEqual(band_of(ranked), "none")

    def test_a_narrow_gap_still_bars_the_strong_band(self):
        """§1.2 and §4.1: two candidates that are one weight apart.

        The file's series is #11, the leader's is #6 and the runner-up's is #11,
        so the leader is one series weight ahead: 1.0000 against 0.9070, a gap
        of 0.0930. That clears 0.08, so this pool is the one where the narrow
        case does *not* bar the band - the case that does is the 2.00 pool in
        `test_a_leader_that_clears_the_score_but_not_the_gap_is_medium`.
        """
        file_book = FileBook(MESSY, LJ, date="2017-07-07")
        ranked = rank(
            file_book,
            [
                CRAGSIDE_RECORD,
                candidate(title=BARE, series_number="11", date="2017-07-07"),
            ],
        )

        self.assertEqual(ranked.matches[0].score, 1.0)
        self.assertAlmostEqual(ranked.matches[1].score, 0.9070, places=4)
        self.assertAlmostEqual(ranked.gap, 0.0930, places=4)
        self.assertEqual(band_of(ranked), "strong")

    def test_a_zero_gap_between_two_records_is_medium(self):
        """§1.2 and §4.1: two records that explain the file equally well.

        Both are the file's own book on title and author and both contradict its
        series position, so both score 0.9070 and the gap is nothing. §4.1 will
        not write whichever of two equal numbers sorted first, and neither
        reaches `singleton_score` either - the pool is refused on both counts.
        """
        file_book = FileBook(MESSY, LJ, date="2017-07-07")
        ranked = rank(
            file_book,
            [
                candidate(title=BARE, series_number="11", date="2017-07-07"),
                candidate(title=BARE, series_number="12", date="2017-07-07"),
            ],
        )

        self.assertAlmostEqual(ranked.matches[0].score, 0.9070, places=4)
        self.assertEqual(ranked.matches[0].score, ranked.matches[1].score)
        self.assertEqual(ranked.gap, 0.0)
        self.assertEqual(band_of(ranked), "medium")

    def test_a_capped_candidate_is_held_at_the_cap_whatever_the_arithmetic(self):
        """§1.3's cap, read as an equality rather than a table row.

        One candidate's author clears the gate, so its author weight stays in
        the denominator and its series and year disagreements give 0.8372. The
        other's does not, so 0.80 leaves the denominator, the title alone scores
        1.0000, and the cap brings it to 0.7000 - which is the number the
        shipped rule's ceiling produced, kept so the log stays comparable. The
        capped one is second, and §4.1 bands the pool on the leader.
        """
        file_book = FileBook(MESSY, LJ, date="2017-07-07")
        ranked = rank(
            file_book,
            [
                candidate(
                    title=BARE, authors=LJ, series_number="11", date="1999-01-01"
                ),
                candidate(
                    title=BARE,
                    authors=("M.J. Porter",),
                    series_number="6",
                    date="2017-07-07",
                ),
            ],
        )

        self.assertEqual(ranked.matches[0].denominator, ALL_FOUR)
        self.assertTrue(ranked.matches[0].author_agrees)
        self.assertAlmostEqual(ranked.matches[0].score, 0.8372, places=4)
        self.assertEqual(ranked.matches[1].denominator, TITLE_SERIES)
        self.assertFalse(ranked.matches[1].author_agrees)
        self.assertEqual(ranked.matches[1].score, NO_AGREEMENT_CEILING)
        self.assertEqual(band_of(ranked), "medium")

    def test_low_and_none_are_different_bands(self):
        """§4.1: low is a score above zero with the author agreeing or not, and
        none is nothing scored at all."""
        file_book = FileBook(MESSY, LJ)
        nothing_alike = candidate(title="The Infirmary", authors=("Carly Reagon",))
        wrong_author = candidate(title="Cragside", authors=("M.J. Porter",))

        self.assertEqual(band_of(rank(file_book, [nothing_alike])), "none")
        self.assertEqual(band_of(rank(file_book, [wrong_author])), "low")

    def test_an_empty_pool_is_none(self):
        """§4.1: `none` is nothing scored, or no candidates at all."""
        self.assertEqual(band_of(rank(FileBook(MESSY, LJ), [])), "none")

    def test_a_capped_candidate_in_a_pool_of_two_is_still_not_strong(self):
        """§1.3: the cap is 0.7 and `strong_score` is 0.89, so a pool of two does
        not let a candidate the author gate refused through."""
        file_book = FileBook(MESSY, LJ)
        capped = candidate(title="Cragside", authors=("M.J. Porter",))
        runner_up = candidate(title="The Infirmary", authors=("Carly Reagon",))

        ranked = rank(file_book, [capped, runner_up])

        self.assertEqual(ranked.matches[0].score, NO_AGREEMENT_CEILING)
        self.assertFalse(ranked.matches[0].author_agrees)
        self.assertEqual(band_of(ranked), "low")

    def test_the_band_is_the_only_thing_band_of_returns(self):
        """§5.2: `band_of(ranked)` returns which band a pool falls in and
        nothing else - it never calls, writes or decides."""
        band = band_of(rank(FileBook(MESSY, LJ), [CRAGSIDE_RECORD]))

        self.assertIsInstance(band, str)
        self.assertIn(band, ("strong", "medium", "low", "none"))

    def test_the_thresholds_the_caller_passes_are_what_draw_the_bands(self):
        """§5.2 and §4.5: the thresholds are the caller's, not this module's.

        One pool, three policies. The candidate is §2.1 row 4 - the file's own
        title and author exactly and the series position disagreeing - which
        scores 0.9070 at §2's full denominator. Under the shipped bands that is
        a singleton short of the 0.95 bar and so medium; a caller's 0.90 bar
        makes the same pool strong; and a caller's 0.95 medium bar pushes it
        down to low. Nothing about the pool changed between the three.
        """
        ranked = rank(
            FileBook(MESSY, LJ, date="2017-07-07"),
            [
                candidate(
                    title="Cragside: A DCI Ryan Mystery",
                    series_number="11",
                    date="2017-07-07",
                )
            ],
        )

        self.assertEqual(ranked.matches[0].denominator, ALL_FOUR)
        self.assertEqual(ranked.matches[0].score, 0.907)
        self.assertEqual(band_of(ranked), "medium")
        self.assertEqual(band_of(ranked, Bands(singleton=0.90)), "strong")
        self.assertEqual(band_of(ranked, Bands(medium=0.95)), "low")

    def test_a_singleton_bar_under_the_strong_one_is_refused(self):
        """§1.2: a pool of one must never be easier to write than a corroborated one."""
        with self.assertRaises(ValueError):
            Bands(strong=0.89, singleton=0.85)


class RankTests(unittest.TestCase):
    """§5.1: the whole ordered pool, and the gap it can be read from."""

    def test_the_pool_comes_back_in_score_order(self):
        file_book = FileBook(MESSY, LJ)
        worse = candidate(
            title="Cragside: A 1930s murder mystery", authors=("M.J. Porter",)
        )
        best = candidate(title="Cragside")
        middling = candidate(title="Cragside", authors=("M.J. Porter",))

        ranked = rank(file_book, [worse, best, middling])

        self.assertEqual(
            [match.candidate for match in ranked.matches], [best, middling, worse]
        )
        self.assertEqual(
            [match.score for match in ranked.matches],
            sorted([match.score for match in ranked.matches], reverse=True),
        )

    def test_ties_keep_the_order_the_source_offered(self):
        """§3.6: ties are broken by input order, which is stable."""
        file_book = FileBook(BARE, LJ)
        first = candidate(title="Cragside")
        second = candidate(title="Cragside")

        ranked = rank(file_book, [first, second])

        self.assertEqual([match.candidate for match in ranked.matches], [first, second])

    def test_a_singleton_pool_has_no_runner_up_and_no_gap(self):
        """§5.1: `Ranked` is the ordered pool plus band, runner-up and gap."""
        ranked = rank(FileBook(BARE, LJ), [candidate(title="Cragside")])

        self.assertEqual(len(ranked.matches), 1)
        self.assertIsNone(ranked.runner_up)
        self.assertIsNone(ranked.gap)
        self.assertEqual(band_of(ranked), "strong")

    def test_the_runner_up_is_the_second_best_and_the_gap_is_the_difference(self):
        """§4.1: the gap is `leader.score - runner_up.score` over the deduped pool."""
        file_book = FileBook(MESSY, LJ, date="2017-07-07")
        runner_up = candidate(title="Cragside", series_number="11", date="2017-07-07")

        ranked = rank(file_book, [CRAGSIDE_RECORD, runner_up])

        self.assertIs(ranked.runner_up, ranked.matches[1])
        self.assertAlmostEqual(
            ranked.gap, ranked.matches[0].score - ranked.matches[1].score, places=4
        )
        self.assertAlmostEqual(ranked.gap, SERIES_W / ALL_FOUR, places=4)

    def test_an_empty_pool_is_not_an_error(self):
        ranked = rank(FileBook(BARE, LJ), [])

        self.assertEqual(ranked.matches, ())
        self.assertIsNone(ranked.runner_up)
        self.assertIsNone(ranked.gap)
        self.assertIsNone(ranked.leader)
        self.assertEqual(band_of(ranked), "none")

    def test_scoring_the_same_pool_twice_is_identical(self):
        """§3.6 and §6 item 16: determinism is a correctness requirement.

        File-level duplicate detection is a byte comparison of the corrected
        book, so two runs over one pool have to order it the same way and grade
        it the same way.
        """
        pool = [
            candidate(title="Cragside", series_number="11", date="2017-07-07"),
            candidate(title="The Infirmary", series_number="11"),
            candidate(title="Cragside", series_number="6", date="2017-07-07"),
            candidate(
                title="Cragside: A 1930s murder mystery", authors=("M.J. Porter",)
            ),
        ]
        file_book = FileBook(MESSY, LJ, date="2017-07-07")

        first = rank(file_book, pool)
        second = rank(file_book, pool)

        self.assertEqual(
            [match.candidate for match in first.matches],
            [match.candidate for match in second.matches],
        )
        self.assertEqual(
            [match.score for match in first.matches], [m.score for m in second.matches]
        )
        self.assertEqual(band_of(first), band_of(second))
        self.assertEqual(first.gap, second.gap)
        self.assertEqual(first.matches[0].denominator, second.matches[0].denominator)


class LanguageFilterTests(unittest.TestCase):
    """§3.5: the matcher drops only what it can prove, and only in one case."""

    def test_differing_codes_of_the_same_form_are_dropped(self):
        """§3.5: both sides two-letter, and the codes differ."""
        ranked = rank(FileBook(BARE, LJ, "en"), [candidate(title=BARE, language="de")])

        self.assertEqual(ranked.matches, ())
        self.assertEqual(band_of(ranked), "none")

    def test_differing_three_letter_codes_are_dropped_too(self):
        """§3.5: the same form, three-letter, and the codes differ."""
        ranked = rank(
            FileBook(BARE, LJ, "eng"), [candidate(title=BARE, language="ger")]
        )

        self.assertEqual(ranked.matches, ())

    def test_the_same_language_in_the_same_form_is_kept(self):
        ranked = rank(FileBook(BARE, LJ, "en"), [candidate(title=BARE, language="en")])

        self.assertEqual(len(ranked.matches), 1)

    def test_a_regional_tag_is_its_primary_code(self):
        """§3.5: `primary_language` strips the region and nothing else."""
        for written, on_the_record in (("en-GB", "en"), ("en", "en-GB"), ("EN", "en")):
            with self.subTest(file=written, record=on_the_record):
                ranked = rank(
                    FileBook(BARE, LJ, written),
                    [candidate(title=BARE, language=on_the_record)],
                )

                self.assertEqual(len(ranked.matches), 1)

    def test_two_letter_against_three_letter_is_kept_and_unflagged(self):
        """§3.5: the matcher cannot decide it, and a wrong drop costs a book."""
        for written, on_the_record in (("en", "eng"), ("eng", "en")):
            with self.subTest(file=written, record=on_the_record):
                ranked = rank(
                    FileBook(BARE, LJ, written),
                    [candidate(title=BARE, language=on_the_record)],
                )

                self.assertEqual(len(ranked.matches), 1)

    def test_a_language_nobody_stated_is_no_evidence_either_way(self):
        for written, on_the_record in ((None, "en"), ("en", None), (None, None)):
            with self.subTest(file=written, record=on_the_record):
                ranked = rank(
                    FileBook(BARE, LJ, written),
                    [candidate(title=BARE, language=on_the_record)],
                )

                self.assertEqual(len(ranked.matches), 1)

    def test_a_dropped_candidate_is_not_counted_as_a_runner_up(self):
        """§4.1: the gap is over the pool, and a dropped record is not in it."""
        wrong_language = candidate(
            title=BARE,
            authors=LJ,
            series_number="6",
            date="2017-07-07",
            language="de",
        )

        ranked = rank(
            FileBook(MESSY, LJ, "en", "2017-07-07"), [CRAGSIDE_RECORD, wrong_language]
        )

        self.assertEqual(len(ranked.matches), 1)
        self.assertIsNone(ranked.runner_up)
        self.assertEqual(band_of(ranked), "strong")


class DedupeTests(unittest.TestCase):
    """§6 item 5 and §5.1: one record described twice is one candidate."""

    def test_one_isbn_thirteen_is_one_record(self):
        """§6 item 5: ISBN-13 equality is the first rule."""
        for isbn in ("9781521748831", "978-1-5217-4883-1", "978 1521748831"):
            with self.subTest(isbn=isbn):
                first = candidate(title=BARE, isbn=isbn)
                second = candidate(title=BARE, isbn=isbn)

                self.assertEqual(dedupe([first, second]), (first,))

    def test_without_an_isbn_the_title_the_first_author_and_the_year_decide(self):
        """§6 item 5's fallback: normalised title + first author + year.

        Two records describing one book, with the year written two ways and the
        author's stops in different places, which §3.1 and §3.4 both collapse.
        """
        first = candidate(title=BARE, authors=LJ, date="2017-07-07")
        second = candidate(title="Cragside", authors=("L.J. Ross",), date="2017")

        self.assertEqual(dedupe([first, second]), (first,))

    def test_a_different_author_is_a_different_record(self):
        first = candidate(title=BARE, authors=LJ)
        second = candidate(title=BARE, authors=("M.J. Porter",))

        self.assertEqual(dedupe([first, second]), (first, second))

    def test_a_different_year_is_a_different_record(self):
        """Same book, two editions: two records until an ISBN says otherwise."""
        first = candidate(title=BARE, authors=LJ, date="2017-07-07")
        second = candidate(title=BARE, authors=LJ, date="1999-01-01")

        self.assertEqual(dedupe([first, second]), (first, second))

    def test_candidates_with_nothing_to_group_on_are_all_kept(self):
        first = candidate(title=None)
        second = candidate(title=None)

        self.assertEqual(dedupe([first, second]), (first, second))

    def test_a_record_with_an_isbn_is_not_grouped_with_one_without(self):
        """The fallback is for records the ISBN cannot group, not a second pass."""
        first = candidate(
            title=BARE, authors=LJ, isbn="9781521748831", date="2017-07-07"
        )
        second = candidate(title=BARE, authors=LJ, date="2017-07-07")

        self.assertEqual(dedupe([first, second]), (first, second))

    def test_the_first_of_a_group_is_the_one_kept(self):
        """§3.6: ties are broken by input order."""
        first = candidate(title=BARE, isbn="9781521748831", source="hardcover")
        second = candidate(title=BARE, isbn="9781521748831", source="google_books")

        self.assertEqual(dedupe([first, second]), (first,))
        self.assertEqual(dedupe([second, first]), (second,))

    def test_dedupe_does_not_reorder_what_it_keeps(self):
        first = candidate(title=BARE, isbn="9781521748831")
        second = candidate(title="Belsay")
        third = candidate(title=BARE, isbn="9781521748831")

        self.assertEqual(dedupe([first, second, third]), (first, second))

    def test_an_empty_pool_is_an_empty_pool(self):
        self.assertEqual(dedupe([]), ())


class TopCandidatesTests(unittest.TestCase):
    """§5.1: the best few by score, and the cap that keeps a prompt to a reply."""

    def test_the_best_few_come_back_best_first(self):
        file_book = FileBook(MESSY, LJ)
        worst = candidate(title="The Infirmary", authors=("Carly Reagon",))
        best = candidate(title="Cragside", authors=("M.J. Porter",))
        middling = candidate(title="The Infirmary", authors=LJ)

        kept = top_candidates(file_book, [worst, best, middling])

        self.assertEqual(kept[0], best)
        self.assertEqual(kept[-1], worst)

    def test_the_cap_is_five_per_source(self):
        """§6 item 9: `CANDIDATES_PER_SOURCE = 5`, per source, before scoring."""
        file_book = FileBook(MESSY, LJ)
        offered = [candidate(title=f"Cragside {number}") for number in range(9)]

        self.assertEqual(len(top_candidates(file_book, offered)), 5)

    def test_the_cap_keeps_the_best_rather_than_the_first(self):
        file_book = FileBook(MESSY, LJ)
        best = candidate(title="Cragside")
        distractors = [
            candidate(title="The Infirmary", authors=("Carly Reagon",))
            for _ in range(6)
        ]

        kept = top_candidates(file_book, distractors + [best])

        self.assertEqual(kept[0], best)

    def test_a_candidate_first_but_weak_is_still_offered(self):
        """§5.1: being ranked is not being accepted - the model sees them all."""
        file_book = FileBook(MESSY, LJ)
        weak = candidate(title="The Infirmary", authors=("Carly Reagon",))

        self.assertEqual(top_candidates(file_book, [weak]), [weak])


class NormaliseIsFrozenTests(unittest.TestCase):
    """§3.7 and §5.1: `normalise` is the record's durable key, and it does not move.

    A characterisation test rather than a specification. The failure it exists
    for is somebody later "tidying" the normalisation, which re-keys every
    stored name in a library and writes a second spelling of every author -
    CBO-41's whole point. It is deliberately not the comparison pipeline:
    `comparison_text` strips accents and articles, and this one does not.
    """

    def test_the_golden_keys(self):
        keys = {
            "L. J. Ross": "lj ross",
            "Ross, L. J.": "ross lj",
            "Ursula K. Le Guin": "ursula k le guin",
            "J.R.R. Tolkien": "jrr tolkien",
            "Brontë": "brontë",
            "Müller": "müller",
            "Cragside (The DCI Ryan Mysteries Book 6)": (
                "cragside the dci ryan mysteries book 6"
            ),
        }
        for written, expected in keys.items():
            with self.subTest(written=written):
                self.assertEqual(normalise(written), expected)

    def test_the_frozen_key_keeps_what_the_comparison_strips(self):
        """The two are different functions on purpose: a durable key is
        conservative, a comparison key is aggressive.

        Accents are the cleanest difference: `normalise` keeps `Brontë` as a
        durable key, and `comparison_text` reads it as `bronte`.
        """
        self.assertEqual(normalise("Brontë"), "brontë")
        self.assertEqual(comparison_text("Brontë"), "bronte")
        self.assertEqual(normalise("The Waste Land"), "the waste land")
        self.assertEqual(comparison_text("The Waste Land"), "waste land")

    def test_the_record_s_own_key_table_still_holds(self):
        """CBO-41's tests in `tests/test_record.py` key on these, and this file
        is where the freeze is stated."""
        self.assertEqual(normalise("LJ Ross"), "lj ross")
        self.assertEqual(normalise("Ross, L. J."), "ross lj")
        self.assertEqual(normalise("1.0.0"), "1 0 0")


class CleaningTests(unittest.TestCase):
    """`clean_title` and the query forms are unchanged: what gets *asked* about
    did not move in this design, only what gets scored."""

    def test_the_series_bracket_is_removed_and_captured(self):
        cleaned = clean_title(MESSY)

        self.assertEqual(
            (cleaned.series, cleaned.series_number), ("The DCI Ryan Mysteries", "6")
        )
        self.assertNotIn("Book 6", cleaned.search)
        self.assertNotIn("DCI Ryan Mysteries", cleaned.search)

    def test_the_subtitle_is_split_off_for_searching(self):
        self.assertEqual(clean_title(MESSY).search, "Cragside")

    def test_a_title_with_no_number_keeps_no_series_number(self):
        cleaned = clean_title("Belsay: A DCI Ryan Mystery")

        self.assertEqual(cleaned.search, "Belsay")
        self.assertIsNone(cleaned.series)
        self.assertIsNone(cleaned.series_number)

    def test_a_bare_number_in_brackets_is_not_a_series_number(self):
        cleaned = clean_title("Cragside (2019)")

        self.assertEqual(cleaned.search, "Cragside (2019)")
        self.assertIsNone(cleaned.series_number)

    def test_a_title_that_says_nothing_extra_is_left_alone(self):
        self.assertEqual(clean_title("Normal People").search, "Normal People")

    def test_a_named_subtitle_is_not_split_off(self):
        """`The Lord of the Rings: The Fellowship of the Ring` names two books."""
        cleaned = clean_title("The Lord of the Rings: The Fellowship of the Ring")

        self.assertEqual(
            cleaned.search, "The Lord of the Rings: The Fellowship of the Ring"
        )

    def test_a_whole_numbered_series_position_keeps_its_number(self):
        cleaned = clean_title("Berwick (The DCI Ryan Mysteries Book 24)")

        self.assertEqual((cleaned.search, cleaned.series_number), ("Berwick", "24"))

    def test_a_fractional_series_position_is_kept_as_it_is(self):
        self.assertEqual(
            clean_title("A Novella (The DCI Ryan Mysteries Book 6.5)").series_number,
            "6.5",
        )

    def test_an_empty_title_is_clean_and_empty_rather_than_an_error(self):
        for title in (None, "", "   "):
            with self.subTest(title=title):
                self.assertEqual(clean_title(title).search, "")
                self.assertIsNone(search_title(title), "a blank title asks nothing")

    def test_the_title_asked_about_is_the_cleaned_one(self):
        self.assertEqual(search_title(MESSY), "Cragside")
        self.assertEqual(search_title("Belsay: A DCI Ryan Mystery"), "Belsay")

    def test_murder_is_not_a_generic_subtitle_word(self):
        """§3.3: `_GENERIC_SUBTITLE` lists `mystery`, so `A 1930s murder mystery`
        strips on `mystery` and on the `a ` rule rather than on `murder`."""
        cleaned = clean_title("Cragside: A 1930s murder mystery")

        self.assertEqual(cleaned.search, "Cragside")
        self.assertEqual(cleaned.also, "Cragside: A 1930s murder mystery")


if __name__ == "__main__":
    unittest.main()
