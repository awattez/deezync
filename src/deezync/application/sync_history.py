from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from deezync.domain.account import DeezerAccount, DeezerProfile
from deezync.domain.listen import Listen

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncReport:
    """Outcome of synchronising one account."""

    account: str
    fetched: int = 0
    created: int = 0
    already_present: int = 0
    failed: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.failed == 0


class SyncHistory:
    """Use case: pull the latest listens of every account into Elasticsearch.

    Accounts are processed one after another: a few API calls per account are
    enough, and staying sequential keeps a comfortable margin under the Deezer
    API quotas. The client is picked per account from `account.auth_method`
    ("oauth" or "arl"), so the flow is identical for both authentication modes.
    """

    def __init__(self, deezer_clients: Mapping[str, object], repository) -> None:
        self._clients = deezer_clients
        self._repository = repository

    def run(self, accounts: Sequence[DeezerAccount]) -> list[SyncReport]:
        self._repository.ensure_index()
        return [self.sync_account(account) for account in accounts]

    def sync_account(self, account: DeezerAccount) -> SyncReport:
        """Sync one account. Failures are caught here so the other accounts still run."""
        try:
            client = self._clients[account.auth_method]
            profile = client.fetch_profile(account)
            entries = client.fetch_history(account, user_id=profile.user_id)
            listens = self._to_listens(entries, account=account, profile=profile)
            result = self._repository.save_all(listens)
        except Exception as exc:
            logger.error("account %s: sync failed (%s)", account.name, exc)
            return SyncReport(account=account.name, error=str(exc))

        return SyncReport(
            account=account.name,
            fetched=len(entries),
            created=result.created,
            already_present=result.already_present,
            failed=result.failed,
        )

    @staticmethod
    def _to_listens(
        entries: Sequence[dict], *, account: DeezerAccount, profile: DeezerProfile
    ) -> list[Listen]:
        listens = []
        for entry in entries:
            try:
                listens.append(
                    Listen.from_history_entry(
                        entry,
                        user=account.name,
                        user_id=profile.user_id,
                        country=profile.country,
                        display_timezone=account.display_timezone,
                    )
                )
            except ValueError as exc:
                logger.warning("account %s: entry skipped (%s)", account.name, exc)
        return listens
