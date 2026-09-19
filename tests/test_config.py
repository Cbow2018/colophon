"""Tests for reading config.toml and applying environment overrides."""

import unittest
from pathlib import Path

from colophon.config import ConfigError, load_config
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
        ]:
            with self.subTest(name=name, value=value), self.assertRaises(ConfigError):
                load_config(env={name: value})

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
