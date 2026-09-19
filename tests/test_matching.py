"""Tests for title cleaning, comparison normalisation and the confidence rule.

The scope's whole point is that a file's title carries things a source does not
have - a subtitle, a series bracket - and that a comparison has to survive the
spelling a file happens to use without ever rewriting it. So the tests below
assert both halves: what the cleaner produces, and that the file's own values
come back untouched.
"""

import unittest

from colophon.correction import TITLE_CONFIDENCE
from colophon.matching import (
    AUTHOR_WEIGHT,
    TITLE_WEIGHT,
    Candidate,
    FileBook,
    best_candidate,
    clean_title,
    nearest_candidate,
    normalise,
    score_candidate,
    search_title,
)

AS_DOWNLOADED = "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)"

# What Hardcover has for that book, as the client hands it over to be scored.
CRAGSIDE = Candidate(
    title="Cragside",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="6",
    language="en",
)

# The other books the recorded Hardcover replies describe: Belsay is #23 on the
# record though its file's title never says so, and The Infirmary is the same
# author's other book.
BELSAY = Candidate(
    title="Belsay",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="23",
    language="en",
)
THE_INFIRMARY = Candidate(
    title="The Infirmary",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="11",
    language="en",
)


def confidence_of(file_title, file_authors=("L. J. Ross",), candidate=CRAGSIDE, language="en"):
    return score_candidate(FileBook(file_title, file_authors, language), candidate)


class CleaningTests(unittest.TestCase):
    def test_the_series_bracket_is_removed_and_captured(self):
        cleaned = clean_title(AS_DOWNLOADED)

        self.assertEqual(
            (cleaned.series, cleaned.series_number), ("The DCI Ryan Mysteries", "6")
        )
        self.assertNotIn("Book 6", cleaned.search)
        self.assertNotIn("DCI Ryan Mysteries", cleaned.search)

    def test_the_subtitle_is_split_off_for_searching(self):
        cleaned = clean_title(AS_DOWNLOADED)

        self.assertEqual(cleaned.search, "Cragside")

    def test_a_title_with_no_number_keeps_no_series_number(self):
        """Belsay is #23 on Hardcover; the file's title never says so."""
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

        self.assertEqual(cleaned.search, "The Lord of the Rings: The Fellowship of the Ring")

    def test_a_whole_numbered_series_position_keeps_its_number(self):
        cleaned = clean_title("Berwick (The DCI Ryan Mysteries Book 24)")

        self.assertEqual((cleaned.search, cleaned.series_number), ("Berwick", "24"))

    def test_a_fractional_series_position_is_kept_as_it_is(self):
        cleaned = clean_title("A Novella (The DCI Ryan Mysteries Book 6.5)")

        self.assertEqual(cleaned.series_number, "6.5")

    def test_an_empty_title_is_clean_and_empty_rather_than_an_error(self):
        for title in (None, "", "   "):
            with self.subTest(title=title):
                self.assertEqual(clean_title(title).search, "")
                self.assertIsNone(search_title(title), "a blank title asks nothing")

    def test_the_title_asked_about_is_the_cleaned_one(self):
        self.assertEqual(search_title(AS_DOWNLOADED), "Cragside")
        self.assertEqual(search_title("Belsay: A DCI Ryan Mystery"), "Belsay")


class NormalisingTests(unittest.TestCase):
    def test_a_name_compares_the_same_however_it_is_spelt(self):
        """The file says `L. J. Ross`; Hardcover says `L.J. Ross`."""
        match = score_candidate(
            FileBook("Cragside", ("L. J. Ross",), "en"),
            Candidate(title="Cragside", authors=("L.J. Ross",), language="en"),
        )

        self.assertEqual(match.author_score, 1.0, "the punctuation must not matter")
        self.assertEqual(match.confidence, 1.0)

    def test_a_surname_first_name_is_the_same_name(self):
        """A record that spells the name the other way round agrees too."""
        match = score_candidate(
            FileBook("Cragside", ("L. J. Ross",), "en"),
            Candidate(title="Cragside", authors=("Ross, L. J.",), language="en"),
        )

        self.assertEqual(match.author_score, 1.0)
        self.assertEqual(match.confidence, 1.0)

    def test_initials_without_stops_still_agree(self):
        """The file says `LJ Ross`; every spelling of the record's name agrees."""
        for record in ("LJ Ross", "L.J. Ross", "L. J. Ross", "Ross, L. J.", "Ross, LJ"):
            with self.subTest(record=record):
                match = score_candidate(
                    FileBook("Cragside", ("LJ Ross",), "en"),
                    Candidate(title="Cragside", authors=(record,), language="en"),
                )

                self.assertEqual(match.author_score, 1.0)
                self.assertEqual(match.confidence, 1.0)

    def test_a_different_author_still_does_not_agree(self):
        """The comma rule must not turn every name into every other name."""
        for record in ("M.J. Porter", "Ross, Carly", "Carly Reagon"):
            with self.subTest(record=record):
                match = score_candidate(
                    FileBook("Cragside", ("LJ Ross",), "en"),
                    Candidate(title="Cragside", authors=(record,), language="en"),
                )

                self.assertEqual(match.author_score, 0.0)

    def test_normalise_keeps_the_words_apart(self):
        """Punctuation is a word break, not something to glue words with."""
        self.assertEqual(normalise("L. J. Ross"), "l j ross")
        self.assertEqual(normalise("L.J. Ross"), "l j ross")
        self.assertEqual(normalise("Ross, L. J."), "ross l j")

    def test_normalising_never_touches_the_value_it_was_given(self):
        """Symbols and accents are stripped for comparison, never for writing."""
        written = "Ursula K. Le Guin"

        self.assertEqual(normalise(written), "ursula k le guin")
        self.assertEqual(written, "Ursula K. Le Guin")

    def test_symbols_and_accents_survive_in_the_written_value(self):
        written = "O'Brien"

        self.assertEqual(normalise(written), "o brien")
        self.assertEqual(written, "O'Brien")


class ConfidenceTests(unittest.TestCase):
    def test_the_two_halves_are_weighted_and_the_title_alone_is_not_enough(self):
        self.assertEqual(TITLE_WEIGHT + AUTHOR_WEIGHT, 1.0)
        self.assertLess(TITLE_WEIGHT, 0.85, "a title match on its own must not be accepted")

    def test_no_candidate_agreeing_on_one_half_alone_can_reach_the_threshold(self):
        """The number and `agrees` must not be able to disagree."""
        files = ("Cragside", "Cragside: A DCI Ryan Mystery")
        candidates = (
            Candidate(title="Cragside", authors=("M.J. Porter",), series_number="6"),
            Candidate(title="Cragside: A DCI Ryan Mystery", authors=("M.J. Porter",)),
            Candidate(title="Cragside", authors=()),
            Candidate(title="The Infirmary", authors=("L.J. Ross",), series_number="11"),
        )
        for file_title in files:
            for candidate in candidates:
                with self.subTest(file=file_title, candidate=candidate.title):
                    match = confidence_of(file_title, candidate=candidate)
                    if not match.agrees:
                        self.assertLess(match.confidence, TITLE_CONFIDENCE)

    def test_a_cleaned_title_and_an_agreeing_author_is_certain(self):
        match = confidence_of(AS_DOWNLOADED)

        self.assertEqual(match.confidence, 1.0)
        self.assertEqual((match.title_score, match.author_score), (1.0, 1.0))
        self.assertTrue(match.agrees)

    def test_a_matching_title_with_a_different_author_does_not_agree(self):
        """The Infirmary is a real book too, but this one is by someone else."""
        match = confidence_of(
            "The Infirmary: A DCI Ryan Mystery",
            candidate=Candidate(title="The Infirmary", authors=("Carly Reagon",), language="en"),
        )

        self.assertEqual(match.title_score, 1.0)
        self.assertEqual(match.author_score, 0.0)
        self.assertLess(match.confidence, 0.85)
        self.assertFalse(match.agrees)

    def test_a_matching_author_with_a_different_title_does_not_agree(self):
        """The lookalike this ticket names: same author, different book of hers."""
        match = confidence_of(
            AS_DOWNLOADED,
            candidate=Candidate(
                title="The Infirmary", authors=("L.J. Ross",), language="en"
            ),
        )

        self.assertEqual(match.title_score, 0.0)
        self.assertEqual(match.author_score, 1.0)
        self.assertLess(match.confidence, 0.85)
        self.assertFalse(match.agrees)

    def test_a_file_that_names_no_author_is_not_matched_on_its_title(self):
        match = confidence_of(AS_DOWNLOADED, file_authors=())

        self.assertEqual(match.author_score, 0.0)
        self.assertLess(match.confidence, 0.85)
        self.assertFalse(match.agrees)

    def test_a_source_that_names_no_author_is_not_matched_on_its_title(self):
        match = confidence_of(AS_DOWNLOADED, candidate=Candidate(title="Cragside"))

        self.assertFalse(match.agrees)

    def test_a_candidate_in_another_language_is_never_the_book(self):
        """Non-English books are matched in their own language, never translated."""
        german = Candidate(title="Cragside", authors=("L.J. Ross",), language="de")

        found = best_candidate(
            FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [german], TITLE_CONFIDENCE
        )

        self.assertIsNone(found)

    def test_a_language_nobody_stated_is_no_evidence_either_way(self):
        self.assertTrue(confidence_of(AS_DOWNLOADED, language=None).agrees)
        self.assertIsNotNone(
            best_candidate(
                FileBook(AS_DOWNLOADED, ("L. J. Ross",), None),
                [Candidate(title="Cragside", authors=("L.J. Ross",), language="en")],
                TITLE_CONFIDENCE,
            )
        )
        self.assertIsNotNone(
            best_candidate(
                FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"),
                [Candidate(title="Cragside", authors=("L.J. Ross",), language=None)],
                TITLE_CONFIDENCE,
            )
        )

    def test_a_regional_language_agrees_with_its_primary_one(self):
        """`en-GB` in the file is `en` on the record, and the same book."""
        for written, on_the_record in (
            ("en-GB", "en"),
            ("en-US", "en"),
            ("EN-gb", "en"),
            ("en", "en-GB"),
        ):
            with self.subTest(written=written, record=on_the_record):
                match = confidence_of(
                    AS_DOWNLOADED,
                    language=written,
                    candidate=Candidate(
                        title="Cragside", authors=("L.J. Ross",), language=on_the_record
                    ),
                )

                self.assertEqual(match.confidence, 1.0)

    def test_a_regional_language_still_does_not_agree_with_another_language(self):
        found = best_candidate(
            FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en-GB"),
            [Candidate(title="Cragside", authors=("L.J. Ross",), language="de-DE")],
            TITLE_CONFIDENCE,
        )

        self.assertIsNone(found)

    def test_a_source_title_that_carries_the_subtitle_on_it_still_agrees(self):
        match = confidence_of(
            "Cragside",
            candidate=Candidate(
                title="Cragside: A DCI Ryan Mystery", authors=("L.J. Ross",), language="en"
            ),
        )

        self.assertEqual(match.title_score, 0.9)
        self.assertGreater(match.confidence, 0.85)
        self.assertTrue(match.agrees)

    def test_a_title_that_merely_starts_the_same_does_not_agree(self):
        match = confidence_of(
            "Crag",
            candidate=Candidate(title="Cragside", authors=("L.J. Ross",), language="en"),
        )

        self.assertEqual(match.title_score, 0.0)
        self.assertFalse(match.agrees)


class SeriesTests(unittest.TestCase):
    """The series number the file's own title carried, used as a check."""

    def test_a_number_the_record_agrees_with_confirms_the_match(self):
        match = confidence_of(AS_DOWNLOADED)

        self.assertEqual(match.confidence, 1.0, "not above 1.0, whatever the nudge")

    def test_a_file_with_no_number_is_no_evidence_either_way(self):
        """Belsay's title carries no number; the record's #23 is not a conflict."""
        match = confidence_of("Belsay: A DCI Ryan Mystery", candidate=BELSAY)

        self.assertEqual(match.confidence, 1.0)

    def test_a_number_the_record_contradicts_costs_but_does_not_veto(self):
        """A wrong position is evidence, but a perfect title and author win.

        The file says book 6 and the record says 11. Both halves of the
        comparison agree exactly, so the position is a doubt rather than a
        contradiction - it is the file's subtitle talking, and a source's own
        numbering is allowed to disagree with a publisher's without the book
        becoming a different book.
        """
        match = confidence_of(
            AS_DOWNLOADED,
            candidate=Candidate(
                title="Cragside", authors=("L.J. Ross",), series_number="11", language="en"
            ),
        )

        self.assertEqual(match.title_score, 1.0, "same title")
        self.assertEqual(match.author_score, 1.0, "and the same person")
        self.assertEqual(match.confidence, 0.9, "0.05 of doubt, under the threshold")
        self.assertGreaterEqual(match.confidence, TITLE_CONFIDENCE)

    def test_a_wrong_number_still_costs_a_match_that_was_only_contained(self):
        """A weaker title cannot afford the doubt the position adds."""
        match = confidence_of(
            AS_DOWNLOADED,
            candidate=Candidate(
                title="Cragside: A DCI Ryan Mystery",
                authors=("L.J. Ross",),
                series_number="11",
                language="en",
            ),
        )

        self.assertEqual(match.title_score, 0.9, "contained, not equal")
        self.assertEqual(match.confidence, 0.84, "0.94 less the doubt")
        self.assertLess(match.confidence, TITLE_CONFIDENCE)

    def test_the_number_picks_between_two_candidates_nothing_else_can(self):
        right = Candidate(title="Berwick", authors=("L.J. Ross",), series_number="24")
        wrong = Candidate(title="Berwick", authors=("L.J. Ross",), series_number="11")

        found = best_candidate(
            FileBook("Berwick (Book 24)", ("L. J. Ross",), "en"),
            [wrong, right],
            TITLE_CONFIDENCE,
        )

        self.assertEqual(found.candidate, right)


class BestCandidateTests(unittest.TestCase):
    def test_the_nearest_candidate_wins(self):
        worse = Candidate(title="Cragside: A DCI Ryan Mystery", authors=("L.J. Ross",))
        best = Candidate(
            title="Cragside",
            authors=("L.J. Ross",),
            series="DCI Ryan Mysteries",
            series_number="6",
            language="en",
        )

        found = best_candidate(
            FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [worse, best], TITLE_CONFIDENCE
        )

        self.assertEqual(found.candidate, best)
        self.assertEqual(found.confidence, 1.0)

    def test_the_right_book_wins_even_when_a_lookalike_is_offered_first(self):
        someone_else = Candidate(title="Cragside", authors=("M.J. Porter",))
        wanted = Candidate(title="Cragside", authors=("L.J. Ross",))

        found = best_candidate(
            FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"),
            [someone_else, wanted],
            TITLE_CONFIDENCE,
        )

        self.assertEqual(found.candidate, wanted)

    def test_a_candidate_agreeing_on_neither_half_is_never_a_match(self):
        nothing_alike = Candidate(title="The Infirmary", authors=("Carly Reagon",))

        self.assertIsNone(
            best_candidate(
                FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [nothing_alike], TITLE_CONFIDENCE
            )
        )
        # It is still the nearest, and still scores nothing: the two are
        # different questions, and the log names one and applies the other.
        nearest = nearest_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [nothing_alike])
        self.assertEqual(nearest.candidate, nothing_alike)
        self.assertFalse(nearest.agrees)
        self.assertEqual(nearest.confidence, 0.0)

    def test_no_candidates_is_no_match_rather_than_an_error(self):
        self.assertIsNone(
            best_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [], TITLE_CONFIDENCE)
        )
        self.assertIsNone(
            nearest_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [])
        )


class NearestCandidateTests(unittest.TestCase):
    """What a book that was passed over is named by in the log."""

    def test_a_near_miss_is_returned_to_be_named(self):
        """The caller applies the threshold; this only says which was nearest."""
        someone_elses = Candidate(title="Cragside", authors=("M.J. Porter",))

        found = nearest_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [someone_elses])

        self.assertEqual(found.candidate, someone_elses)
        self.assertLess(found.confidence, TITLE_CONFIDENCE)
        self.assertEqual(found.why, "same title; no author agrees")

    def test_the_threshold_is_what_the_match_has_to_clear(self):
        someone_elses = Candidate(title="Cragside", authors=("M.J. Porter",))

        self.assertIsNone(
            best_candidate(
                FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [someone_elses], TITLE_CONFIDENCE
            )
        )


if __name__ == "__main__":
    unittest.main()
