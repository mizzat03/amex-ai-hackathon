"""Separately persisted human review model with optimistic version checks."""

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.contracts.enums import HumanReviewStatus


class VersionConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HumanReviewRecord:
    incident_id: str
    hypothesis_id: str
    status: HumanReviewStatus
    note: str | None
    reviewed_by: str
    updated_at: datetime
    version: int


class HumanReviewStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], HumanReviewRecord] = {}

    def put(
        self,
        incident_id: str,
        hypothesis_id: str,
        status: HumanReviewStatus | str,
        note: str | None,
        expected_version: int,
    ) -> HumanReviewRecord:
        status = HumanReviewStatus(status)
        key = (incident_id, hypothesis_id)
        existing = self._records.get(key)
        current_version = existing.version if existing else 1
        if expected_version != current_version:
            raise VersionConflict(
                f"expected review version {expected_version}, current version is {current_version}"
            )
        clean_note = note.strip() if note else None
        if status in {HumanReviewStatus.REJECTED, HumanReviewStatus.INCONCLUSIVE} and not clean_note:
            raise ValueError("rejected or inconclusive review requires a non-empty note")
        record = HumanReviewRecord(
            incident_id=incident_id,
            hypothesis_id=hypothesis_id,
            status=status,
            note=clean_note,
            reviewed_by="demo-operator",
            updated_at=datetime.now(UTC),
            version=current_version + 1,
        )
        self._records[key] = record
        return record
