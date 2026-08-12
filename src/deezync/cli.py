from __future__ import annotations

import argparse
import logging
import sys

from elasticsearch import Elasticsearch

from deezync import __version__
from deezync.application.sync_history import SyncHistory, SyncReport
from deezync.config import ConfigError, Settings, load_accounts, load_settings
from deezync.infrastructure.deezer_client import DeezerClient
from deezync.infrastructure.deezer_gw_client import DeezerGwClient
from deezync.infrastructure.listen_repository import ListenRepository

logger = logging.getLogger("deezync")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    try:
        settings = load_settings(args.users)
        accounts = load_accounts(settings.users_file)
    except ConfigError as exc:
        logger.error("configuration: %s", exc)
        return 2

    clients = {"oauth": DeezerClient(), "arl": DeezerGwClient()}
    reports = SyncHistory(clients, _build_repository(settings)).run(accounts)
    _print_summary(reports, settings)
    return 0 if all(report.ok for report in reports) else 1


def _build_repository(settings: Settings) -> ListenRepository:
    client = Elasticsearch(
        settings.es_url,
        api_key=settings.es_api_key,
        basic_auth=(
            (settings.es_username, settings.es_password)
            if settings.es_username and settings.es_password
            else None
        ),
    )
    return ListenRepository(client, settings.es_index)


def _print_summary(reports: list[SyncReport], settings: Settings) -> None:
    for report in reports:
        if report.error:
            logger.error("%-16s failed: %s", report.account, report.error)
        else:
            logger.info(
                "%-16s %3d listens read, %3d new, %3d already indexed%s",
                report.account,
                report.fetched,
                report.created,
                report.already_present,
                f", {report.failed} failed" if report.failed else "",
            )
    total = sum(report.created for report in reports)
    logger.info("%d new listen(s) indexed into %s", total, settings.es_index)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="deezync",
        description="Sync Deezer listening history into Elasticsearch.",
    )
    parser.add_argument(
        "--users",
        metavar="PATH",
        help="TOML file listing the accounts (default: users.toml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    parser.add_argument("--version", action="version", version=f"deezync {__version__}")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
