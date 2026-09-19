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
# how a source is disabled. The order is also the default order a user gets.
KNOWN_SOURCES = ("hardcover", "google_books")

# The rules a metadata field can be given, in the order the design spec lists
# them, and what each means: leave the file's value alone, write the source's
# value only when the file has none, or write it whatever the file has.
FIELD_RULES = ("skip", "fill", "overwrite")

# Every field Colophon can write, and the rule it gets unless the user says
# otherwise. The defaults are the design spec's own list, with one deliberate
# reading of it: `fill` is judged against the file, so a book that already
# carries a value keeps it even when `overwrite` would have changed it. A field
# here that no source can supply is not an error - `fill` on a field the source
# is silent about simply writes nothing.
FIELD_DEFAULTS = (
    ("title", "overwrite"),
    ("authors", "overwrite"),
    ("series", "overwrite"),
    ("series_number", "overwrite"),
    ("description", "fill"),
    ("publisher", "fill"),
    ("date", "fill"),
    ("isbn", "fill"),
    ("language", "fill"),
)

# Every field Colophon can write, in the order the log line names them. The
# mapping in `Config.fields` is keyed by exactly these names, and a test holds
# the two together so a field cannot exist in one list and not the other.
KNOWN_FIELDS = tuple(name for name, _ in FIELD_DEFAULTS)

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
    sources: tuple = KNOWN_SOURCES
    # What to do with each metadata field, as (field, rule) pairs: `skip`,
    # `fill` or `overwrite`. Every field is present, so a rule is never missing
    # at the point it is applied.
    fields: tuple = FIELD_DEFAULTS
    # Whether to add a cover to a book that has none. A book that already has
    # one keeps it: that is what the setting means, so there is no rule to set.
    add_cover: bool = True
    # How sure a title-and-author match has to be before it is written, as the
    # design spec's own 0.85. At 1.0 only a match nothing can be doubted about is
    # accepted, which is a title and an author that both agree exactly - that
    # scores exactly 1.0 - so the setting can turn the title path off and leave
    # the ISBN path without being a value nothing could ever reach.
    confidence: float = 0.85


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
    values["fields"] = _to_fields(values.pop("fields", {}))
    values["add_cover"] = _to_bool(
        _setting(env, values, "add_cover", bool), "add_cover"
    )
    values["confidence"] = _to_confidence(
        _setting(env, values, "confidence", (int, float))
    )

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


def _to_confidence(value):
    """A confidence threshold: a fraction above zero and no more than one.

    Zero is refused because a threshold nothing can fail is not a threshold, and
    anything above one is refused because no match can reach it - the comparison
    caps a candidate at 1.0 - so either would silently turn matching off or on
    rather than meaning what it says.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"confidence should be a number, not {value!r}") from error
    if not 0 < number <= 1:
        raise ConfigError(
            f"confidence should be above 0 and at most 1, not {number:g}"
        )
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


def _to_fields(given):
    """Every field's rule: the user's where they set one, the default otherwise.

    A misspelt field name is refused rather than ignored. It would otherwise be
    a rule the user believes is running and that never runs at all, which is the
    one failure of this setting that is invisible from the outside. A rule named
    without regard to case is accepted, because this is a setting people write
    by hand.
    """
    if not isinstance(given, dict):
        raise ConfigError("fields should be a table, e.g. [fields] title = \"skip\"")

    rules = dict(FIELD_DEFAULTS)
    for field, rule in given.items():
        if field not in rules:
            raise ConfigError(
                f"fields names {field!r}, which is not a field Colophon has; "
                "expected one of " + ", ".join(KNOWN_FIELDS)
            )
        chosen = str(rule).strip().lower()
        if chosen not in FIELD_RULES:
            raise ConfigError(
                f"{field} is set to {rule!r}, which is not a rule; expected one of "
                + ", ".join(FIELD_RULES)
            )
        rules[field] = chosen
    return tuple(rules.items())
