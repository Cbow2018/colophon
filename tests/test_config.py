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
