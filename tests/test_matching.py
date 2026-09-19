"""Tests for title cleaning, comparison normalisation and the confidence rule.

The scope's whole point is that a file's title carries things a source does not
have - a subtitle, a series bracket - and that a comparison has to survive the
spelling a file happens to use without ever rewriting it. So the tests below
assert both halves: what the cleaner produces, and that the file's own values
come back untouched.
"""

import unittest

from colophon.matching import (
    AUTHOR_WEIGHT,
    TITLE_WEIGHT,
    Candidate,
    FileBook,
    best_candidate,
    clean_title,
    compared,
    normalise,
    title_variants,
)

# The metadata a file arrives with, and what Hardcover has for the same book.
AS_DOWNLOADED = "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)"
CRAGSIDE = Candidate(
    title="Cragside",
    authors=("L.J. Ross",),
    series="DCI Ryan Mysteries",
    series_number="6",
    language="en",
)


def confidence_of(file_title, file_authors=("L. J. Ross",), candidate=CRAGSIDE, language="en"):
    return compared(FileBook(file_title, file_authors, language), candidate)


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
        self.assertEqual(cleaned.subtitle, "A DCI Ryan Mystery")

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
        cleaned = clean_title("Normal People")

        self.assertEqual(cleaned.search, "Normal People")
        self.assertIsNone(cleaned.subtitle)

    def test_a_named_subtitle_is_not_split_off(self):
        """`The Lord of the Rings: The Fellowship of the Ring` names two books."""
        cleaned = clean_title("The Lord of the Rings: The Fellowship of the Ring")

        self.assertEqual(cleaned.search, "The Lord of the Rings: The Fellowship of the Ring")
        self.assertIsNone(cleaned.subtitle)

    def test_a_whole_numbered_series_position_keeps_its_number(self):
        cleaned = clean_title("Berwick (The DCI Ryan Mysteries Book 24)")

        self.assertEqual((cleaned.search, cleaned.series_number), ("Berwick", "24"))

    def test_a_fractional_series_position_is_kept_as_it_is(self):
        cleaned = clean_title("A Novella (The DCI Ryan Mysteries Book 6.5)")

        self.assertEqual(cleaned.series_number, "6.5")

    def test_an_empty_title_is_clean_and_empty_rather_than_an_error(self):
        for title in (None, "", "   "):
            with self.subTest(title=title):
                self.assertEqual(title_variants(title), [])
                self.assertEqual(clean_title(title).search, "")

    def test_the_titles_asked_about_are_the_cleaned_one(self):
        self.assertEqual(title_variants(AS_DOWNLOADED), ["Cragside"])
        self.assertEqual(title_variants("Belsay: A DCI Ryan Mystery"), ["Belsay"])


class NormalisingTests(unittest.TestCase):
    def test_a_name_compares_the_same_however_it_is_spelt(self):
        """The file says `L. J. Ross`; Hardcover says `L.J. Ross`."""
        match = compared(
            FileBook("Cragside", ("L. J. Ross",), "en"),
            Candidate(title="Cragside", authors=("L.J. Ross",), language="en"),
        )

        self.assertEqual(match.author_score, 1.0, "the punctuation must not matter")
        self.assertEqual(match.confidence, 1.0)

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

        found = best_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [german])

        self.assertIsNone(found)

    def test_a_language_nobody_stated_is_no_evidence_either_way(self):
        self.assertTrue(confidence_of(AS_DOWNLOADED, language=None).agrees)
        self.assertIsNotNone(
            best_candidate(
                FileBook(AS_DOWNLOADED, ("L. J. Ross",), None),
                [Candidate(title="Cragside", authors=("L.J. Ross",), language="en")],
            )
        )
        self.assertIsNotNone(
            best_candidate(
                FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"),
                [Candidate(title="Cragside", authors=("L.J. Ross",), language=None)],
            )
        )

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


class BestCandidateTests(unittest.TestCase):
    def test_the_best_agreeing_candidate_wins(self):
        worse = Candidate(title="Cragside: A DCI Ryan Mystery", authors=("L.J. Ross",))
        best = Candidate(title="Cragside", authors=("L.J. Ross",), series="DCI Ryan Mysteries")

        found = best_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [worse, best])

        self.assertEqual(found[0], best)
        self.assertEqual(found[1].confidence, 1.0)

    def test_a_candidate_whose_author_disagrees_is_passed_over(self):
        someone_else = Candidate(title="Cragside", authors=("M.J. Porter",))
        wanted = Candidate(title="Cragside", authors=("L.J. Ross",))

        found = best_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), [someone_else, wanted])

        self.assertEqual(found[0], wanted)

    def test_a_title_alone_is_left_for_someone_else(self):
        found = best_candidate(
            FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"),
            [Candidate(title="Cragside", authors=("M.J. Porter",))],
        )

        self.assertIsNone(found)

    def test_no_candidates_is_no_match_rather_than_an_error(self):
        self.assertIsNone(best_candidate(FileBook(AS_DOWNLOADED, ("L. J. Ross",), "en"), []))


if __name__ == "__main__":
    unittest.main()
