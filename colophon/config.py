"""Settings for the relay: read from config.toml, overridden by the environment.

Secrets never come from the environment (see the design spec); every setting
here is a plain, non-secret one, so an environment override is safe.
"""

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from colophon.matching import normalise

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

# Where Colophon's own record lives: the SQLite file holding the author and
# series spellings a library has settled on. It cannot live beside `config.toml`
# because that folder is mounted read-only, so it goes in the backups folder,
# which is the one place this program is already sure it can write and whose
# cleanup leaves a dotted name alone. It should point at local disk: SQLite's
# locking is unreliable over SMB or NFS.
DEFAULT_RECORD_PATH = "/backups/.colophon.db"

# The rules a metadata field can be given, in the order the design spec lists
# them, and what each means: leave the file's value alone, write the source's
# value only when the file has none, or write it whatever the file has.
FIELD_RULES = ("skip", "fill", "overwrite")

# How sure a title-and-author match has to be before it is written, unless the
# user says otherwise. Three thresholds, and the bands they draw:
#
# * `DEFAULT_STRONG_SCORE` is the multi-candidate bar. A pool of two or more is
#   written when its best candidate clears it and is separated from the runner-up
#   by the gap.
# * `DEFAULT_SINGLETON_SCORE` is the bar for a pool of one, which has no
#   runner-up to corroborate it and so has to be near-exact on everything the
#   file states.
# * `DEFAULT_MEDIUM_SCORE` is where the LLM tiebreaker starts. A candidate under
#   the strong bar but over this one is a question worth asking; under it, the
#   book is marked unverified without a call.
#
# `strong_score` and `medium_score` are **provisional** and move when the
# thresholds are tuned against a real library (`docs/research/cbo-58.md` §4.4).
DEFAULT_STRONG_SCORE = 0.89
DEFAULT_SINGLETON_SCORE = 0.95
DEFAULT_MEDIUM_SCORE = 0.80

# Every field Colophon can write, and the rule it gets unless the user says
# otherwise. The defaults are the design spec's own list, with one deliberate
# reading of it: `fill` is judged against the file, so a book that already
# carries a value keeps it even when `overwrite` would have changed it. A field
# here that no source can supply is not an error - `fill` on a field the source
# is silent about simply writes nothing.
#
# A rule is judged against the file's own value as well as the source's, and
# `overwrite` writes a value the file does not already carry in another form:
# a title whose comparison key is the file's own is the same title, and is not
# written over. An author is the exception - an author's identity is the
# Record's business rather than the comparison's, so a spelling the Record
# settled on always reaches the file. `correction._edits` states both in full.
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

# The retry windows, as a number and a unit. `0` is the one bare number that is
# a duration of its own - it says do not hold - and the units are lower case
# only, so `24H` is a refusal rather than a guess at which one was meant. The
# digits are `[0-9]` rather than `\d`, which is Unicode-aware and would read
# `٢٤h` as a duration.
_DURATION = re.compile(r"([0-9]+)([mhd])?")
_UNIT_SECONDS = {"m": 60, "h": 60 * 60, "d": 24 * 60 * 60}

# The default window, written the two ways it is needed: a user copies the
# duration into config.toml, and `Config` holds the seconds the parser makes of
# it. Both windows default to this.
DEFAULT_RETRY = "24h"
DEFAULT_RETRY_SECONDS = 86400

# A default whose value a user writes in another form is given that form here
# too, for the same reason: `Config` holds a retry window as seconds, so reading
# the default off the dataclass would hand the parser a number and refuse it.
# Every other setting reads its default off `Config`, which is what a user
# writes anyway.
_RAW_DEFAULTS = {"source_retry": DEFAULT_RETRY, "llm_retry": DEFAULT_RETRY}


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
    # The LLM fallback chooser: which OpenAI-compatible endpoint to ask when the
    # rules cannot decide. One default key file for every provider, because a
    # per-provider default means switching provider silently means renaming the
    # Docker secret, and it is easy to end up with no LLM without noticing. An
    # empty base URL or model means the preset's own.
    llm_provider: str = "deepseek"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_key_file: Path = Path("/run/secrets/llm_key")
    # How many calls a UTC day may spend. 0 means no limit. The count itself
    # lives beside the backups, in the hidden file `colophon.llm.COUNTER_NAME`
    # names: that folder is already writable, already created, and already
    # protected from deletion, and a setting for one internal path would be
    # deployment surface for nothing (Q13).
    llm_daily_limit: int = 200
    # Which sources to consult, in order. Both paths - the ISBN one and the
    # title one - walk this same list.
    sources: tuple = KNOWN_SOURCES
    # What to do with each metadata field, as (field, rule) pairs: `skip`,
    # `fill` or `overwrite`. Every field is present, so a rule is never missing
    # at the point it is applied.
    fields: tuple = FIELD_DEFAULTS
    # The spellings the user insists on, as (normalised spelling, what to write)
    # pairs: `[authors]` `"LJ Ross" = "L.J. Ross"`. The keys are normalised so
    # that every way of writing one name reaches the same entry, and these beat
    # whatever the record settled on — which is what lets a person fix a
    # spelling in their library app and have it stick.
    authors: tuple = ()
    # The user's own tag list, as the spellings to write. A source's genres are
    # judged against these and nothing else, so this is the only vocabulary that
    # ever reaches a book: an empty list means genres are not written at all, and
    # is a fresh install's state rather than a mistake.
    allowed_genres: tuple = ()
    # Where the record is kept. See `DEFAULT_RECORD_PATH` for why it is not
    # beside `config.toml`.
    record_path: Path = Path(DEFAULT_RECORD_PATH)
    # Whether to add a cover to a book that has none. A book that already has
    # one keeps it: that is what the setting means, so there is no rule to set.
    add_cover: bool = True
    # The three thresholds the bands are drawn from, and what each means, are on
    # `DEFAULT_STRONG_SCORE` above. All three are policy - how cautious the user
    # wants their own library corrected - rather than calibration, which is why
    # they are settings and the weights, the gap and the author floor are not.
    strong_score: float = DEFAULT_STRONG_SCORE
    singleton_score: float = DEFAULT_SINGLETON_SCORE
    medium_score: float = DEFAULT_MEDIUM_SCORE
    # Whether to put a book to the LLM whenever the rules could not decide it,
    # rather than only when it landed in the medium band. On, a low or none band
    # book is asked about too, which is the reach the walk had before the bands
    # existed - so this is the default, and turning it off is the deliberate
    # narrowing rather than the other way round. It widens which uncertain books
    # reach the model; it does not disable early exit, and it does not make a
    # book the rules already graded strong spend a call.
    llm_full_scan: bool = True
    # How long a book waits for a source, or for the LLM, before it goes on
    # without it, each as a number of seconds. The two are separate because a
    # provider being topped up or a local model rebooting is a different wait
    # from a source outage. Nothing reads them yet: the schedule and the
    # pass-through are CBO-80's, and the fallback is CBO-82's.
    source_retry: int = DEFAULT_RETRY_SECONDS
    llm_retry: int = DEFAULT_RETRY_SECONDS


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
    values["llm_provider"] = (
        str(_setting(env, values, "llm_provider", str)).strip().lower()
    )
    values["llm_base_url"] = str(_setting(env, values, "llm_base_url", str)).strip()
    values["llm_model"] = str(_setting(env, values, "llm_model", str)).strip()
    values["llm_key_file"] = Path(_setting(env, values, "llm_key_file", str))
    values["llm_daily_limit"] = _to_call_limit(
        _setting(env, values, "llm_daily_limit", int)
    )
    values["sources"] = _to_sources(_setting(env, values, "sources", list))
    values["fields"] = _to_fields(values.pop("fields", {}))
    values["authors"] = _to_authors(values.pop("authors", {}))
    values["allowed_genres"] = _to_genres(_setting(env, values, "allowed_genres", list))
    values["record_path"] = Path(_setting(env, values, "record_path", str))
    values["add_cover"] = _to_bool(
        _setting(env, values, "add_cover", bool), "add_cover"
    )
    for name in ("strong_score", "singleton_score", "medium_score"):
        values[name] = _to_threshold(_setting(env, values, name, (int, float)), name)
    if values["singleton_score"] < values["strong_score"]:
        # Each of the two is a setting on its own, so only the pair can catch an
        # inverted configuration - and an inverted one is not a preference: it
        # makes a pool of one, which nothing corroborates, easier to write from
        # than a pool of two.
        raise ConfigError(
            f"singleton_score ({values['singleton_score']}) is below strong_score "
            f"({values['strong_score']}); a pool of one would then be easier to "
            "write than a corroborated one"
        )
    values["llm_full_scan"] = _to_bool(
        _setting(env, values, "llm_full_scan", bool), "llm_full_scan"
    )
    # Both windows arrive as a duration string - `"24h"` - except that `0` in
    # TOML is an int, which is the one bare number that is a duration.
    for name in ("source_retry", "llm_retry"):
        values[name] = _to_retry_seconds(_setting(env, values, name, (str, int)), name)

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
    """The environment value if there is one, else the file value, else the default.

    `expected_type` is what the file is allowed to write, and it can be a tuple
    for a setting that takes more than one kind of value - the retry windows
    take a duration string and the bare integer `0`. The environment is never
    checked here: it is always a string, and each setting's own reader is what
    decides whether the text means anything.
    """
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
    return _RAW_DEFAULTS.get(name, getattr(Config, name))


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


def _to_threshold(value, name):
    """A band threshold: a fraction above zero and no more than one.

    Zero is refused because a threshold nothing can fail is not a threshold, and
    anything above one is refused because no match can reach it - the comparison
    caps a candidate at 1.0 - so either would silently turn matching off or on
    rather than meaning what it says.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name} should be a number, not {value!r}") from error
    if not 0 < number <= 1:
        raise ConfigError(f"{name} should be above 0 and at most 1, not {number:g}")
    return number


def _to_retry_seconds(value, name):
    """A retry window as a number of seconds: `"90m"`, or `0` for do not hold.

    The one number that carries its own unit is zero, and the file writes it as
    a TOML integer, so the text of both that and `"0"` is read the same way.
    A bare number with any other value is refused rather than guessed at:
    `source_retry = 24` could be a day or twenty-four seconds, and either guess
    would be a window the user did not ask for. Upper case is refused for the
    same reason - the settings say which units exist, and nothing else is a
    duration.
    """
    match = _DURATION.fullmatch(str(value).strip())
    if match is None or match.group(2) is None and match.group(1) != "0":
        raise ConfigError(
            f"{name} should be a number and a unit - m, h or d, as in 90m or 24h "
            f"- or 0 to not wait at all, not {value!r}"
        )
    if match.group(2) is None:
        return 0
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def _to_call_limit(value):
    """A daily call limit: a whole number of calls, or 0 for no limit at all.

    Zero is allowed and means what it says, so this cannot be `_to_positive_int`:
    a user who does not want a limit has to be able to say so.
    """
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(
            f"llm_daily_limit should be a whole number, not {value!r}"
        ) from error
    if number < 0:
        raise ConfigError(f"llm_daily_limit cannot be negative, not {number}")
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
            "sources should name at least one source, e.g. " + ", ".join(KNOWN_SOURCES)
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


def _to_authors(given):
    """The `[authors]` overrides, keyed by the normalised spelling of a name.

    A name is written half a dozen ways across the sources and the files, and
    the user should only have to name it once, so the key is `normalise`'s
    output rather than the characters they typed. Two keys that normalise to the
    same name are one name with two answers, and TOML gives no order to appeal
    to — so which one won would be the parser's business, and it is refused
    instead. A key that normalises to nothing is refused for the same reason: it
    could never match a name at all.
    """
    if not isinstance(given, dict):
        raise ConfigError('authors should be a table, e.g. [authors]\n"LJ" = "..."')

    overrides = {}
    written_as = {}
    for key, value in given.items():
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(
                f"authors names {key!r} as {value!r}, which is not a spelling to "
                "write; expected a non-empty string"
            )
        normalised = normalise(key)
        if not normalised:
            raise ConfigError(
                f"authors has a key {key!r} that is not a name, so it could never "
                "match one"
            )
        if normalised in overrides and overrides[normalised] != value:
            raise ConfigError(
                f"authors names {written_as[normalised]!r} and {key!r} as two "
                f"different spellings, {overrides[normalised]!r} and {value!r}; "
                "they are the same name, so which one wins would depend on the "
                "order they were written in"
            )
        overrides[normalised] = value
        written_as[normalised] = key
    return tuple(overrides.items())


def _to_genres(value):
    """The allowed genres, as the spellings to write, in the order they are given.

    An environment variable arrives as one comma-separated string, config.toml as
    a list of strings. Two entries that are one genre spelt two ways are refused,
    for the reason `_to_authors` records: there is no order to appeal to, so
    which spelling won would be whichever the parser happened to keep.
    """
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    genres = []
    written_as = {}
    for part in parts:
        if not isinstance(part, str) or not part.strip():
            raise ConfigError(
                f"allowed_genres names {part!r}, which is not a genre to write; "
                "expected a non-empty string"
            )
        key = part.strip().casefold()
        if key in written_as:
            raise ConfigError(
                f"allowed_genres names {written_as[key]!r} and {part!r}, which are "
                "the same genre spelt two ways; they are one genre, so which one "
                "wins would depend on the order they were written in"
            )
        written_as[key] = part
        genres.append(part.strip())
    return tuple(genres)


def _to_fields(given):
    """Every field's rule: the user's where they set one, the default otherwise.

    A misspelt field name is refused rather than ignored. It would otherwise be
    a rule the user believes is running and that never runs at all, which is the
    one failure of this setting that is invisible from the outside. A rule named
    without regard to case is accepted, because this is a setting people write
    by hand.
    """
    if not isinstance(given, dict):
        raise ConfigError('fields should be a table, e.g. [fields] title = "skip"')

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
