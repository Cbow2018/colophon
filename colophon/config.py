"""Settings for the relay: read from config.toml, overridden by the environment.

Secrets never come from the environment (see the design spec); every setting
here is a plain, non-secret one, so an environment override is safe.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import tomllib

DEFAULT_CONFIG_PATH = "/config/config.toml"

# Endings that mean a download or copy is still in progress. Files whose names
# start with a dot are skipped too, which covers our own temporary files.
DEFAULT_SKIP_SUFFIXES = (".part", ".tmp", ".!qb", ".crdownload")

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Where metadata is looked up, in the order the user wants them tried. The list
# covers every field: it is a trust order, not a per-field preference, so a book
# takes its values from the first source that matches it. Leaving a name out is
# how a source is disabled.
KNOWN_SOURCES = ("hardcover", "google_books")
DEFAULT_SOURCES = KNOWN_SOURCES

_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off")


class ConfigError(Exception):
    """A setting is missing, misspelt or unusable."""


@dataclass(frozen=True)
class Config:
    ingest_dir: Path = Path("/ingest")
    output_dir: Path = Path("/output")
    backup_dir: Path = Path("/backups")
    dry_run: bool = True
    poll_seconds: float = 5.0
    stable_checks: int = 2
    log_level: str = "INFO"
    skip_suffixes: tuple = DEFAULT_SKIP_SUFFIXES
    # Originals are kept this long before the backups folder is cleared out.
    backup_retention_days: int = 30
    # Where the Docker secret holding the Hardcover token is mounted. A file
    # that is not there means no ISBN lookups happen at all, which is fine.
    hardcover_token_file: Path = Path("/run/secrets/hardcover_token")
    # The same for Google Books. Unlike Hardcover's token this one is required
    # for the source to work at all: Google gives a keyless caller no queries.
    google_books_key_file: Path = Path("/run/secrets/google_books_key")
    # Which sources to consult, in order. Both paths - the ISBN one and the
    # title one - walk this same list.
    sources: tuple = DEFAULT_SOURCES


def load_config(env=None):
    """Build a Config from config.toml and the environment.

    Precedence: environment variable, then config.toml, then the default.
    """
    env = os.environ if env is None else env
    path = Path(env.get("COLOPHON_CONFIG", DEFAULT_CONFIG_PATH))
    values = _read_file(path)

    for name in ("ingest_dir", "output_dir", "backup_dir"):
        values[name] = Path(_setting(env, values, name, str))
    values["dry_run"] = _to_bool(_setting(env, values, "dry_run", bool), "dry_run")
    values["poll_seconds"] = _to_positive_float(
        _setting(env, values, "poll_seconds", (int, float)), "poll_seconds"
    )
    values["stable_checks"] = _to_positive_int(
        _setting(env, values, "stable_checks", int), "stable_checks"
    )
    values["log_level"] = _to_log_level(_setting(env, values, "log_level", str))
    values["skip_suffixes"] = _to_suffixes(
        _setting(env, values, "skip_suffixes", list), "skip_suffixes"
    )
    values["backup_retention_days"] = _to_positive_int(
        _setting(env, values, "backup_retention_days", int), "backup_retention_days"
    )
    values["hardcover_token_file"] = Path(
        _setting(env, values, "hardcover_token_file", str)
    )
    values["google_books_key_file"] = Path(
        _setting(env, values, "google_books_key_file", str)
    )
    values["sources"] = _to_sources(_setting(env, values, "sources", list))

    return Config(**values)


def _read_file(path):
    """Return the settings in config.toml, or an empty dict if there is no file."""
    try:
        with open(path, "rb") as handle:
            values = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise ConfigError(f"could not read {path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error

    known = set(Config.__dataclass_fields__)
    for name in values:
        if name not in known:
            raise ConfigError(
                f"{path} has an unknown setting {name!r}; expected one of "
                + ", ".join(sorted(known))
            )
    return values


def _setting(env, values, name, expected_type):
    """The environment value if there is one, else the file value, else the default."""
    from_env = env.get("COLOPHON_" + name.upper())
    if from_env is not None:
        return from_env
    if name in values:
        value = values[name]
        if not isinstance(value, expected_type) or isinstance(value, bool) != (
            expected_type is bool
        ):
            raise ConfigError(f"{name} in config.toml has the wrong kind of value")
        return value
    return getattr(Config, name)


def _to_bool(value, name):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ConfigError(f"{name} should be true or false, not {value!r}")


def _to_positive_float(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} should be a number, not {value!r}") from error
    if number <= 0:
        raise ConfigError(f"{name} should be greater than zero, not {number}")
    return number


def _to_positive_int(value, name):
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} should be a whole number, not {value!r}") from error
    if number < 1:
        raise ConfigError(f"{name} should be at least 1, not {number}")
    return number


def _to_log_level(value):
    level = str(value).strip().upper()
    if level not in LOG_LEVELS:
        raise ConfigError(
            f"log_level should be one of {', '.join(LOG_LEVELS)}, not {value!r}"
        )
    return level


def _to_suffixes(value, name):
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    suffixes = tuple(str(part).strip().lower() for part in parts if str(part).strip())
    for suffix in suffixes:
        if not suffix.startswith("."):
            raise ConfigError(f"{name} entries should start with a dot, not {suffix!r}")
    return suffixes


def _to_sources(value):
    """The source names to consult, checked against the ones Colophon knows.

    An environment variable arrives as one comma-separated string, config.toml
    as a list of strings. Names are matched without regard to case, because the
    setting is read by hand as often as it is written by hand.
    """
    if isinstance(value, str):
        names = value.split(",")
    else:
        names = list(value)
    sources = tuple(str(name).strip().lower() for name in names if str(name).strip())

    if not sources:
        raise ConfigError(
            "sources should name at least one source, e.g. "
            + ", ".join(KNOWN_SOURCES)
        )
    for name in sources:
        if name not in KNOWN_SOURCES:
            raise ConfigError(
                f"sources names {name!r}, which is not a source Colophon has; "
                "expected one of " + ", ".join(KNOWN_SOURCES)
            )
    if len(set(sources)) != len(sources):
        # Trying one source twice would ask it the same question twice and, on a
        # good day, get the same answer: it is a typo, not an intention.
        repeated = next(name for name in sources if sources.count(name) > 1)
        raise ConfigError(f"sources names {repeated!r} more than once")
    return sources
