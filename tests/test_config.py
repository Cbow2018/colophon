"""Tests for reading config.toml and applying environment overrides."""

import unittest
from pathlib import Path

from colophon.config import (
    FIELD_DEFAULTS,
    KNOWN_SOURCES,
    ConfigError,
    load_config,
)
from tests.tempdir import TemporaryDirectory


class LoadConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_config(self, text):
        path = self.tmp / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_defaults_when_no_file_and_no_environment(self):
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(config.ingest_dir, Path("/ingest"))
        self.assertEqual(config.output_dir, Path("/output"))
        self.assertEqual(config.backup_dir, Path("/backups"))
        self.assertTrue(config.dry_run)
        self.assertEqual(config.poll_seconds, 5.0)
        self.assertEqual(config.stable_checks, 2)
        self.assertEqual(config.log_level, "INFO")
        self.assertIn(".part", config.skip_suffixes)
        self.assertEqual(config.backup_retention_days, 30)
        self.assertEqual(
            config.hardcover_token_file, Path("/run/secrets/hardcover_token")
        )
        self.assertEqual(
            config.google_books_key_file, Path("/run/secrets/google_books_key")
        )

    def test_the_sources_are_tried_in_the_order_the_user_sets(self):
        """Hardcover first, then Google Books, unless the user says otherwise."""
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(config.sources, ("hardcover", "google_books"))

    def test_a_source_left_out_of_the_list_is_disabled(self):
        path = self.write_config('sources = ["google_books"]\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(config.sources, ("google_books",))

    def test_the_user_can_reorder_the_list(self):
        path = self.write_config('sources = ["google_books", "hardcover"]\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(config.sources, ("google_books", "hardcover"))

    def test_the_environment_can_set_the_list_too(self):
        config = load_config(env={"COLOPHON_SOURCES": "google_books"})

        self.assertEqual(config.sources, ("google_books",))

    def test_a_source_nobody_has_heard_of_is_rejected(self):
        path = self.write_config('sources = ["open_library"]\n')

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("open_library", str(caught.exception))
        self.assertIn(
            "google_books", str(caught.exception), "it lists what it does know"
        )

    def test_a_source_named_twice_is_rejected(self):
        path = self.write_config('sources = ["hardcover", "hardcover"]\n')

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("hardcover", str(caught.exception))

    def test_an_empty_list_is_rejected(self):
        """No sources at all is a misconfiguration, not a quiet pass-through."""
        path = self.write_config("sources = []\n")

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("at least one source", str(caught.exception))

    def test_a_source_name_is_read_regardless_of_case(self):
        path = self.write_config('sources = ["Hardcover"]\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(config.sources, ("hardcover",))

    def test_the_google_books_key_comes_from_a_secret_file_path(self):
        config = load_config(
            env={
                "COLOPHON_CONFIG": str(self.tmp / "missing.toml"),
                "COLOPHON_GOOGLE_BOOKS_KEY_FILE": "/run/secrets/books_key",
            }
        )

        self.assertEqual(config.google_books_key_file, Path("/run/secrets/books_key"))

    def test_the_hardcover_token_comes_from_a_secret_file_path(self):
        config = load_config(
            env={
                "COLOPHON_CONFIG": str(self.tmp / "missing.toml"),
                "COLOPHON_HARDCOVER_TOKEN_FILE": "/run/secrets/hardcover",
                "COLOPHON_BACKUP_RETENTION_DAYS": "7",
            }
        )

        self.assertEqual(config.hardcover_token_file, Path("/run/secrets/hardcover"))
        self.assertEqual(config.backup_retention_days, 7)

    def test_file_values_replace_defaults(self):
        path = self.write_config(
            """
            ingest_dir = "/books/in"
            output_dir = "/books/out"
            backup_dir = "/books/backups"
            dry_run = false
            poll_seconds = 1.5
            stable_checks = 4
            log_level = "DEBUG"
            skip_suffixes = [".part", ".nzb"]
            """
        )

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(config.ingest_dir, Path("/books/in"))
        self.assertEqual(config.output_dir, Path("/books/out"))
        self.assertEqual(config.backup_dir, Path("/books/backups"))
        self.assertFalse(config.dry_run)
        self.assertEqual(config.poll_seconds, 1.5)
        self.assertEqual(config.stable_checks, 4)
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.skip_suffixes, (".part", ".nzb"))

    def test_environment_beats_file(self):
        path = self.write_config('ingest_dir = "/books/in"\ndry_run = false\n')

        config = load_config(
            env={
                "COLOPHON_CONFIG": str(path),
                "COLOPHON_INGEST_DIR": "/elsewhere",
                "COLOPHON_DRY_RUN": "true",
                "COLOPHON_POLL_SECONDS": "0.25",
                "COLOPHON_STABLE_CHECKS": "3",
                "COLOPHON_LOG_LEVEL": "warning",
                "COLOPHON_SKIP_SUFFIXES": ".part, .crdownload",
            }
        )

        self.assertEqual(config.ingest_dir, Path("/elsewhere"))
        self.assertTrue(config.dry_run)
        self.assertEqual(config.poll_seconds, 0.25)
        self.assertEqual(config.stable_checks, 3)
        self.assertEqual(config.log_level, "WARNING")
        self.assertEqual(config.skip_suffixes, (".part", ".crdownload"))

    def test_booleans_accept_the_usual_spellings(self):
        for text, expected in [
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ]:
            with self.subTest(text=text):
                config = load_config(env={"COLOPHON_DRY_RUN": text})
                self.assertIs(config.dry_run, expected)

    def test_skip_suffixes_are_lowercased(self):
        config = load_config(env={"COLOPHON_SKIP_SUFFIXES": ".!qB,.PART"})

        self.assertEqual(config.skip_suffixes, (".!qb", ".part"))

    def test_unreadable_values_are_rejected(self):
        for name, value in [
            ("COLOPHON_DRY_RUN", "maybe"),
            ("COLOPHON_POLL_SECONDS", "soon"),
            ("COLOPHON_POLL_SECONDS", "0"),
            ("COLOPHON_STABLE_CHECKS", "0"),
            ("COLOPHON_STABLE_CHECKS", "lots"),
            ("COLOPHON_LOG_LEVEL", "chatty"),
            ("COLOPHON_BACKUP_RETENTION_DAYS", "0"),
            ("COLOPHON_BACKUP_RETENTION_DAYS", "ages"),
            ("COLOPHON_STRONG_SCORE", "certain"),
            ("COLOPHON_STRONG_SCORE", "0"),
            ("COLOPHON_STRONG_SCORE", "1.5"),
            ("COLOPHON_STRONG_SCORE", "-0.1"),
            ("COLOPHON_SINGLETON_SCORE", "certain"),
            ("COLOPHON_SINGLETON_SCORE", "0"),
            ("COLOPHON_MEDIUM_SCORE", "1.5"),
            ("COLOPHON_LLM_FULL_SCAN", "maybe"),
        ]:
            with self.subTest(name=name, value=value), self.assertRaises(ConfigError):
                load_config(env={name: value})

    def test_the_three_thresholds_default_to_the_design_s_own_numbers(self):
        """§4.1: `strong_score` 0.89, `singleton_score` 0.95, `medium_score` 0.80.

        The first and the third are provisional and move in §4.4's tuning pass;
        the numbers here are the ones the design ships with.
        """
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(config.strong_score, 0.89)
        self.assertEqual(config.singleton_score, 0.95)
        self.assertEqual(config.medium_score, 0.80)
        self.assertFalse(config.llm_full_scan, "the flag ships off")

    def test_the_old_confidence_key_is_gone_rather_than_aliased(self):
        """§4.5: renaming it is the point, so a stale key is refused, not read."""
        path = self.write_config("confidence = 0.9\n")

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})

    def test_the_thresholds_can_be_set_in_the_file_or_the_environment(self):
        path = self.write_config("strong_score = 0.9\nmedium_score = 0.75\n")

        from_file = load_config(env={"COLOPHON_CONFIG": str(path)})
        from_env = load_config(env={"COLOPHON_STRONG_SCORE": "0.7"})

        self.assertEqual(from_file.strong_score, 0.9)
        self.assertEqual(from_file.medium_score, 0.75)
        self.assertEqual(from_env.strong_score, 0.7, "the environment wins")

    def test_a_singleton_bar_below_the_strong_one_is_refused(self):
        """§1.2: a pool of one must never be easier to write than a corroborated one.

        Each threshold is a setting on its own, so the pair is the only place
        the inversion can be caught - and it is caught at startup rather than at
        the first book, because a config that quietly makes a one-witness pool
        the easiest thing in the library to write is a config that has inverted
        the rule the singleton bar exists for.
        """
        for env in (
            {"COLOPHON_SINGLETON_SCORE": "0.85"},
            {"COLOPHON_STRONG_SCORE": "0.9", "COLOPHON_SINGLETON_SCORE": "0.85"},
        ):
            with self.subTest(env=env), self.assertRaises(ConfigError):
                load_config(env=env)

        equal = load_config(
            env={"COLOPHON_STRONG_SCORE": "0.9", "COLOPHON_SINGLETON_SCORE": "0.9"}
        )

        self.assertEqual(equal.singleton_score, 0.9, "level with it is not below it")

    def test_a_threshold_of_one_is_allowed_because_a_perfect_match_is_reachable(self):
        """The range is `(0, 1]`, and the top of it is a setting rather than a wall.

        A title and an author that both agree exactly score exactly 1.0, so 1.0
        refuses everything else without being a value nothing can reach. The
        boundary is tested from both sides: 1.0 is accepted, and just above it is
        refused because no candidate could ever clear it.

        Both bars are set to 1.0, because a singleton bar below the strong one is
        refused: at strong 1.0 the shipped 0.95 would make a pool of one the
        easiest thing in the library to write from.
        """
        config = load_config(
            env={"COLOPHON_STRONG_SCORE": "1.0", "COLOPHON_SINGLETON_SCORE": "1.0"}
        )

        self.assertEqual(config.strong_score, 1.0)
        for refused in ("1.0000001", "1.5"):
            with self.subTest(given=refused), self.assertRaises(ConfigError):
                load_config(
                    env={
                        "COLOPHON_STRONG_SCORE": refused,
                        "COLOPHON_SINGLETON_SCORE": "1.0",
                    }
                )

    def test_every_field_has_a_rule_and_the_defaults_are_the_ones_documented(self):
        """The design spec's own list, which is what a fresh install gets."""
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(
            dict(config.fields),
            {
                "title": "overwrite",
                "authors": "overwrite",
                "series": "overwrite",
                "series_number": "overwrite",
                "description": "fill",
                "publisher": "fill",
                "date": "fill",
                "isbn": "fill",
                "language": "fill",
            },
        )

    def test_a_cover_is_added_only_if_the_book_has_none_by_default(self):
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertTrue(config.add_cover)

    def test_the_cover_setting_can_be_turned_off(self):
        path = self.write_config("add_cover = false\n")

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertFalse(config.add_cover)

    def test_the_environment_can_turn_the_cover_off_too(self):
        config = load_config(env={"COLOPHON_ADD_COVER": "off"})

        self.assertFalse(config.add_cover)

    def test_the_fields_table_sets_one_rule_at_a_time(self):
        path = self.write_config('[fields]\ntitle = "skip"\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(dict(config.fields)["title"], "skip")
        self.assertEqual(
            dict(config.fields)["series"], "overwrite", "the rest keep their defaults"
        )
        self.assertEqual(len(config.fields), 9, "and nothing is lost")

    def test_every_rule_can_be_set(self):
        path = self.write_config(
            """
            [fields]
            title = "skip"
            authors = "fill"
            series = "overwrite"
            series_number = "skip"
            description = "overwrite"
            publisher = "fill"
            date = "skip"
            isbn = "overwrite"
            language = "fill"
            """
        )

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(
            dict(config.fields),
            {
                "title": "skip",
                "authors": "fill",
                "series": "overwrite",
                "series_number": "skip",
                "description": "overwrite",
                "publisher": "fill",
                "date": "skip",
                "isbn": "overwrite",
                "language": "fill",
            },
        )

    def test_a_rule_nobody_has_heard_of_is_rejected(self):
        path = self.write_config('[fields]\ntitle = "replace"\n')

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("replace", str(caught.exception))
        self.assertIn("overwrite", str(caught.exception), "it lists the rules it knows")

    def test_a_field_nobody_has_heard_of_is_rejected(self):
        """A misspelt field would otherwise be a rule that silently never runs."""
        path = self.write_config('[fields]\ndiscription = "fill"\n')

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("discription", str(caught.exception))
        self.assertIn(
            "description", str(caught.exception), "it lists the fields it knows"
        )

    def test_a_rule_is_read_regardless_of_case(self):
        path = self.write_config('[fields]\ntitle = "Skip"\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(dict(config.fields)["title"], "skip")

    def test_the_example_config_is_one_that_loads_and_says_what_it_claims(self):
        """People copy this file, so it has to be a valid one.

        Every rule and the cover setting are shown commented out, so what the
        file demonstrates is what the defaults already do rather than what it
        sets. A setting written after a `[fields]` header belongs to that table
        in TOML, which is a mistake this file has already made once: `add_cover`
        written below the table is rejected as a field name nobody has.
        """
        example = Path(__file__).resolve().parent.parent / "config.example.toml"
        written = example.read_text(encoding="utf-8")

        config = load_config(env={"COLOPHON_CONFIG": str(example)})

        self.assertEqual(
            dict(config.fields),
            dict(FIELD_DEFAULTS),
            "a copied example changes nothing until the user edits it",
        )
        self.assertEqual(config.sources, KNOWN_SOURCES)
        self.assertTrue(config.add_cover)
        self.assertEqual(
            config.strong_score, 0.89, "the example's threshold is the default"
        )
        self.assertEqual(config.singleton_score, 0.95)
        self.assertEqual(config.medium_score, 0.80)
        self.assertFalse(config.llm_full_scan)
        self.assertTrue(config.dry_run, "the example ships as a dry run")
        self.assertEqual(
            config.allowed_genres, (), "and with no tags list, as it ships"
        )
        for name in (
            "add_cover",
            "strong_score",
            "singleton_score",
            "medium_score",
            "llm_full_scan",
            "title",
            "language",
            "allowed_genres",
        ):
            with self.subTest(setting=name):
                self.assertIn(f"# {name} = ", written, "shown, and commented out")

    def test_the_rules_the_example_shows_are_the_ones_the_code_defaults_to(self):
        """Uncommenting the example has to be a no-op, not a change.

        The file is the only place a user reads what the defaults are, so a
        default changed in the code and not in the file would be a lie told to
        everyone who copies it.
        """
        example = Path(__file__).resolve().parent.parent / "config.example.toml"
        names = {name for name, _ in FIELD_DEFAULTS}
        shown = {}
        for line in example.read_text(encoding="utf-8").splitlines():
            stripped = line.removeprefix("# ").strip()
            name, separator, rule = stripped.partition(" = ")
            if separator and name in names:
                shown[name] = rule.strip().strip('"')

        self.assertEqual(
            shown,
            dict(FIELD_DEFAULTS),
            "the example shows every field and every default",
        )

    def test_unknown_setting_in_the_file_is_rejected(self):
        path = self.write_config('ingset_dir = "/typo"\n')

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})

    def test_broken_toml_is_rejected(self):
        path = self.write_config("ingest_dir = /unquoted\n")

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})


class RecordPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_config(self, text):
        path = self.tmp / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_default_is_beside_the_backups(self):
        """`/config` is mounted read-only, so it cannot live beside config.toml."""
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(config.record_path, Path("/backups/.colophon.db"))

    def test_the_file_can_say_where_it_goes(self):
        path = self.write_config('record_path = "/data/colophon.db"\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(config.record_path, Path("/data/colophon.db"))

    def test_the_environment_can_say_too(self):
        config = load_config(env={"COLOPHON_RECORD_PATH": "/somewhere/else.db"})

        self.assertEqual(config.record_path, Path("/somewhere/else.db"))


class AuthorOverrideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_config(self, text):
        path = self.tmp / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_no_table_means_no_overrides(self):
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(dict(config.authors), {})

    def test_a_table_maps_a_spelling_to_the_one_to_write(self):
        path = self.write_config('[authors]\n"LJ Ross" = "L.J. Ross"\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(dict(config.authors), {"lj ross": "L.J. Ross"})

    def test_the_keys_are_normalised_so_every_spelling_of_one_name_matches(self):
        """TOML keys are literal strings; `L.J.` and `L. J.` are one name here."""
        path = self.write_config('[authors]\n"L. J. Ross" = "L.J. Ross"\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("lj ross", dict(config.authors))
        self.assertNotIn("l j ross", dict(config.authors), "the raw key is not kept")

    def test_two_keys_for_one_name_with_different_values_are_refused(self):
        """There is no order to appeal to, so which won would be the parser's."""
        path = self.write_config(
            '[authors]\n"LJ Ross" = "First"\n"L.J. Ross" = "Second"\n'
        )

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("LJ Ross", str(caught.exception))

    def test_two_keys_for_one_name_agreeing_are_fine(self):
        path = self.write_config(
            '[authors]\n"LJ Ross" = "L.J. Ross"\n"L.J. Ross" = "L.J. Ross"\n'
        )

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(dict(config.authors), {"lj ross": "L.J. Ross"})

    def test_an_empty_value_is_refused(self):
        path = self.write_config('[authors]\n"LJ Ross" = ""\n')

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})

    def test_a_value_that_is_not_a_string_is_refused(self):
        path = self.write_config('[authors]\n"LJ Ross" = 6\n')

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})

    def test_a_key_that_normalises_to_nothing_is_refused(self):
        """`"..."` is not a name, so it could never match one."""
        path = self.write_config('[authors]\n"..." = "L.J. Ross"\n')

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})


class AllowedGenreTests(unittest.TestCase):
    """The user's own tag list, which a source's genres are mapped onto."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_config(self, text):
        path = self.tmp / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_an_empty_list_is_the_default_and_turns_genres_off(self):
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(config.allowed_genres, ())

    def test_the_file_gives_the_list_in_the_order_it_is_written(self):
        path = self.write_config('allowed_genres = ["Crime", "Mystery"]\n')

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(config.allowed_genres, ("Crime", "Mystery"))

    def test_the_environment_can_set_the_list_too(self):
        config = load_config(env={"COLOPHON_ALLOWED_GENRES": "Crime, Mystery"})

        self.assertEqual(config.allowed_genres, ("Crime", "Mystery"))

    def test_an_empty_list_is_not_a_mistake(self):
        """It is how a user says "do not write genres at all"."""
        path = self.write_config("allowed_genres = []\n")

        config = load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertEqual(config.allowed_genres, ())

    def test_two_entries_that_are_one_genre_are_refused(self):
        """There is no order to appeal to, so which won would be the parser's."""
        path = self.write_config('allowed_genres = ["Crime", "crime"]\n')

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("Crime", str(caught.exception))

    def test_an_entry_that_is_not_a_string_is_refused(self):
        path = self.write_config("allowed_genres = [6]\n")

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})

    def test_an_empty_entry_is_refused(self):
        """No genre trims to nothing, so one that does could never be written."""
        path = self.write_config('allowed_genres = ["Crime", "  "]\n')

        with self.assertRaises(ConfigError):
            load_config(env={"COLOPHON_CONFIG": str(path)})


if __name__ == "__main__":
    unittest.main()
