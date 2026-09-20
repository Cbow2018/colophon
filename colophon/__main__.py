"""Entry point: python -m colophon."""

import logging
import os
import signal
import sys
import threading

from colophon.config import ConfigError, load_config
from colophon.record import Record, RecordError
from colophon.relay import Relay, RelayError

LOG = logging.getLogger("colophon")

# The one thing this program does that cannot be undone. It is a flag rather
# than a subcommand because there are no other subcommands to be consistent
# with, and because `--reset-record` says what it does at the point it is typed.
RESET_RECORD = "--reset-record"
ASSUME_YES = "--yes"

# What answers "yes" to the question. Anything else, including nothing at all,
# is a no: a container with no terminal reading EOF must not wipe a record
# because nobody was there to object.
_YES = ("y", "yes")


def main(env=None, stop=None, argv=(), stdin=None):
    """Run the relay, or empty the record, according to `argv`.

    `argv` is the arguments after the program name and defaults to none of them,
    so a caller that does not pass any — a test, or an embedder — gets the relay
    rather than whatever happened to be on the command line.
    """
    setup_logging("INFO")
    argv = list(argv)
    stdin = sys.stdin if stdin is None else stdin

    unknown = [one for one in argv if one not in (RESET_RECORD, ASSUME_YES)]
    if unknown:
        LOG.error(
            "unrecognised argument%s %s; the only ones are %s and %s",
            "" if len(unknown) == 1 else "s",
            ", ".join(unknown),
            RESET_RECORD,
            ASSUME_YES,
        )
        return 2

    try:
        config = load_config(env)
    except ConfigError as error:
        LOG.error("bad setting: %s", error)
        return 1
    LOG.setLevel(config.log_level)

    if RESET_RECORD in argv:
        return reset_record(config, assume_yes=ASSUME_YES in argv, stdin=stdin)

    # Windows, where this is only ever developed, has no user or group ids.
    uid = os.getuid() if hasattr(os, "getuid") else None
    gid = os.getgid() if hasattr(os, "getgid") else None

    LOG.info(
        "Colophon starting: uid=%s gid=%s, ingest %s -> output %s, backups %s, "
        "dry run %s",
        uid,
        gid,
        config.ingest_dir,
        config.output_dir,
        config.backup_dir,
        "on" if config.dry_run else "off",
    )
    warn_if_root(uid)

    try:
        record = Record.open(config.record_path)
    except RecordError as error:
        LOG.error("%s", error)
        return 1
    # Closed on the way out of `main` rather than at the end of the loop, so the
    # command above never leaves a file open and a failure below still shuts it.
    try:
        relay = Relay(config, record=record)
        try:
            relay.prepare()
        except RelayError as error:
            LOG.error("%s", error)
            return 1

        if stop is None:
            stop = threading.Event()
            for caught in (signal.SIGTERM, signal.SIGINT):
                signal.signal(caught, lambda *_: stop.set())

        run(relay, config.poll_seconds, stop)
        LOG.info("Colophon stopped")
        return 0
    finally:
        record.close()


def reset_record(config, assume_yes=False, stdin=None):
    """Empty the record, after asking — unless told not to ask.

    The record is never cleared automatically, so this is the only thing that
    empties it and it is deliberately hard to do by accident: the question names
    the file and counts what is about to go. `--yes` is for a script, and a
    non-interactive stdin is a no rather than a hang, because a container has
    nobody to answer.
    """
    try:
        record = Record.open(config.record_path)
    except RecordError as error:
        LOG.error("%s", error)
        return 1

    try:
        held = record.names()
        if not held:
            LOG.info("nothing to reset: %s is already empty", config.record_path)
            return 0
        if not assume_yes and not _confirmed(stdin or sys.stdin, config, held):
            LOG.info("left %s as it was", config.record_path)
            return 1
        record.reset()
        LOG.info(
            "reset %s: %d name%s forgotten, and the next book by each author sets "
            "the spelling again",
            config.record_path,
            len(held),
            "" if len(held) == 1 else "s",
        )
        return 0
    finally:
        record.close()


def _confirmed(stdin, config, held):
    """Ask, and read one line. Anything but a yes is a no."""
    kinds = sorted({kind for kind, _, _, _, _ in held})
    print(
        f"{config.record_path} holds {len(held)} name(s) "
        f"({', '.join(kinds)}), which is how your library spells them. "
        "Reset it? [y/N] ",
        end="",
        flush=True,
    )
    answer = ""
    try:
        answer = stdin.readline()
    except (OSError, ValueError):
        # No terminal, or one that has gone away: nobody said yes.
        return False
    return answer.strip().lower() in _YES


def run(relay, poll_seconds, stop):
    """Scan the ingest folder until asked to stop."""
    while not stop.is_set():
        relay.scan_once()
        stop.wait(poll_seconds)


def warn_if_root(uid):
    if uid == 0:
        LOG.warning(
            "running as root; set user: \"PUID:PGID\" in docker compose so books "
            "come out owned by you"
        )


def setup_logging(level):
    """One line per book, to stdout, where docker logs picks it up."""
    if not LOG.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
    LOG.setLevel(level)


if __name__ == "__main__":
    sys.exit(main(argv=sys.argv[1:]))
