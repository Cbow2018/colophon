"""Entry point: python -m colophon."""

import logging
import os
import signal
import sys
import threading

from colophon.config import ConfigError, load_config
from colophon.relay import Relay, RelayError

LOG = logging.getLogger("colophon")


def main(env=None, stop=None):
    setup_logging("INFO")
    try:
        config = load_config(env)
    except ConfigError as error:
        LOG.error("bad setting: %s", error)
        return 1
    LOG.setLevel(config.log_level)

    LOG.info(
        "Colophon starting: uid=%s gid=%s, ingest %s -> output %s, backups %s, "
        "dry run %s",
        os.getuid(),
        os.getgid(),
        config.ingest_dir,
        config.output_dir,
        config.backup_dir,
        "on" if config.dry_run else "off",
    )
    warn_if_root(os.getuid())

    relay = Relay(config)
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
    sys.exit(main())
