"""Parameterized PostgreSQL persistence boundary for canonical evidence JSONB."""

from typing import Any, Protocol

from backend.evidence.builder import EvidencePackage


class AsyncConnection(Protocol):
    async def execute(self, query: str, *args: object) -> str: ...

    async def fetchrow(self, query: str, *args: object) -> Any: ...


class PostgresEvidencePackageRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def save(self, package: EvidencePackage) -> None:
        await self._connection.execute(
            """
            INSERT INTO evidence_packages (
                evidence_package_id, incident_id, package_version, completeness,
                schema_version, builder_configuration_version, generated_at, package_json
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            ON CONFLICT (evidence_package_id, package_version) DO NOTHING
            """,
            package.evidence_package_id,
            package.incident_id,
            package.package_version,
            package.completeness.value,
            package.schema_version,
            package.builder_configuration_version,
            package.generated_at,
            package.model_dump_json(),
        )

    async def get_exact(
        self,
        incident_id: str,
        evidence_package_id: str,
        package_version: int,
    ) -> EvidencePackage | None:
        row = await self._connection.fetchrow(
            """
            SELECT package_json
            FROM evidence_packages
            WHERE incident_id = $1
              AND evidence_package_id = $2
              AND package_version = $3
            """,
            incident_id,
            evidence_package_id,
            package_version,
        )
        return EvidencePackage.model_validate(row["package_json"]) if row else None

    async def latest_eligible(
        self,
        incident_id: str,
        completeness: tuple[str, ...] = ("COMPLETE", "PARTIAL"),
    ) -> EvidencePackage | None:
        row = await self._connection.fetchrow(
            """
            SELECT package_json
            FROM evidence_packages
            WHERE incident_id = $1
              AND completeness = ANY($2::text[])
            ORDER BY package_version DESC, generated_at DESC
            LIMIT 1
            """,
            incident_id,
            list(completeness),
        )
        return EvidencePackage.model_validate(row["package_json"]) if row else None
