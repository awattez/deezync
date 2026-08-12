from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from typing import Any

from elasticsearch import Elasticsearch, helpers

from deezync.domain.listen import Listen


def load_index_mapping() -> dict[str, Any]:
    """The index definition: settings and mappings, tuned for this workload."""
    raw = resources.files("deezync.infrastructure").joinpath("index_mapping.json")
    return json.loads(raw.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SaveResult:
    """Outcome of a bulk write."""

    created: int = 0
    already_present: int = 0
    failed: int = 0


class ListenRepository:
    """Stores listens in Elasticsearch.

    Writes use `create` with the deterministic listen id: re-indexing a listen that is
    already stored returns a 409, which is counted rather than treated as a failure.
    """

    def __init__(
        self,
        client: Elasticsearch,
        index: str,
        chunk_size: int = 500,
    ) -> None:
        self._client = client
        self._index = index
        self._chunk_size = chunk_size

    def ensure_index(self) -> bool:
        """Create the index with its mapping if missing. Returns True when created."""
        if self._client.indices.exists(index=self._index):
            return False
        self._client.indices.create(index=self._index, **load_index_mapping())
        return True

    def save_all(self, listens: Iterable[Listen]) -> SaveResult:
        actions = [self._to_action(listen) for listen in listens]
        if not actions:
            return SaveResult()

        created, errors = helpers.bulk(
            self._client,
            actions,
            chunk_size=self._chunk_size,
            raise_on_error=False,
        )
        duplicates = sum(1 for error in errors if _status_of(error) == 409)
        return SaveResult(
            created=created,
            already_present=duplicates,
            failed=len(errors) - duplicates,
        )

    def _to_action(self, listen: Listen) -> dict[str, Any]:
        document = listen.to_document()
        return {
            "_op_type": "create",
            "_index": self._index,
            "_id": document["id"],
            "_source": document,
        }


def _status_of(error: Any) -> int | None:
    if not isinstance(error, dict):
        return None
    for outcome in error.values():
        if isinstance(outcome, dict):
            return outcome.get("status")
    return None
