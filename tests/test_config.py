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
        self.assertIn("google_books", str(caught.exception), "it lists what it does know")

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
            ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
            ("false", False), ("FALSE", False), ("0", False), ("no", False), ("off", False),
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
            ("COLOPHON_CONFIDENCE", "certain"),
            ("COLOPHON_CONFIDENCE", "0"),
            ("COLOPHON_CONFIDENCE", "1.5"),
            ("COLOPHON_CONFIDENCE", "-0.1"),
        ]:
            with self.subTest(name=name, value=value), self.assertRaises(ConfigError):
                load_config(env={name: value})

    def test_the_confidence_threshold_defaults_to_the_design_spec_s_085(self):
        config = load_config(env={"COLOPHON_CONFIG": str(self.tmp / "missing.toml")})

        self.assertEqual(config.confidence, 0.85)

    def test_the_threshold_can_be_set_in_the_file_or_the_environment(self):
        path = self.write_config("confidence = 0.9\n")

        from_file = load_config(env={"COLOPHON_CONFIG": str(path)})
        from_env = load_config(env={"COLOPHON_CONFIDENCE": "0.7"})

        self.assertEqual(from_file.confidence, 0.9)
        self.assertEqual(from_env.confidence, 0.7, "the environment wins")

    def test_a_threshold_of_one_is_allowed_because_a_perfect_match_is_reachable(self):
        """1.0 means 'only a match nothing can be doubted about', which happens.

        A title and an author that both agree exactly score exactly 1.0, so 1.0 is
        a setting rather than a threshold nothing can clear.
        """
        config = load_config(env={"COLOPHON_CONFIDENCE": "1.0"})

        self.assertEqual(config.confidence, 1.0)

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
        path = self.write_config("[fields]\ntitle = \"skip\"\n")

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
        path = self.write_config("[fields]\ntitle = \"replace\"\n")

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("replace", str(caught.exception))
        self.assertIn("overwrite", str(caught.exception), "it lists the rules it knows")

    def test_a_field_nobody_has_heard_of_is_rejected(self):
        """A misspelt field would otherwise be a rule that silently never runs."""
        path = self.write_config("[fields]\ndiscription = \"fill\"\n")

        with self.assertRaises(ConfigError) as caught:
            load_config(env={"COLOPHON_CONFIG": str(path)})

        self.assertIn("discription", str(caught.exception))
        self.assertIn("description", str(caught.exception), "it lists the fields it knows")

    def test_a_rule_is_read_regardless_of_case(self):
        path = self.write_config("[fields]\ntitle = \"Skip\"\n")

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
        self.assertEqual(config.confidence, 0.85, "the example's threshold is the default")
        self.assertTrue(config.dry_run, "the example ships as a dry run")
        for name in ("add_cover", "confidence", "title", "language"):
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


if __name__ == "__main__":
    unittest.main()
