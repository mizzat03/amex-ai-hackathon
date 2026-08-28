"""Deterministic metadata retrieval over a small approved synthetic runbook set."""

from dataclasses import dataclass
from pathlib import Path

from backend.contracts.api import RunbookCitationRef


@dataclass(frozen=True, slots=True)
class RunbookSection:
    citation: RunbookCitationRef
    runbook_title: str
    section_title: str
    approved_guidance_excerpt: str
    tags: frozenset[str]
    cautions: tuple[str, ...]
    guidance_not_incident_proof: bool = True


class RunbookRepository:
    def __init__(self, sections: tuple[RunbookSection, ...]) -> None:
        self._sections = sections
        self._by_ref = {
            (
                item.citation.runbook_id,
                item.citation.runbook_version,
                item.citation.section_id,
            ): item
            for item in sections
        }

    @classmethod
    def from_directory(cls, directory: str | Path) -> "RunbookRepository":
        base = Path(directory).resolve()
        sections: list[RunbookSection] = []
        for path in sorted(base.glob("*.md")):
            if base not in path.resolve().parents:
                raise ValueError("runbook path escaped the approved directory")
            sections.extend(cls._parse(path))
        return cls(tuple(sections))

    def search(self, tags: set[str], limit: int = 3) -> list[RunbookSection]:
        if limit < 1 or limit > 10:
            raise ValueError("runbook result limit must be between 1 and 10")
        normalized = {tag.strip().lower() for tag in tags if tag.strip()}
        ranked = sorted(
            self._sections,
            key=lambda item: (len(normalized & item.tags), item.citation.section_id),
            reverse=True,
        )
        return [item for item in ranked if normalized & item.tags][:limit]

    def resolve(self, citation: RunbookCitationRef) -> RunbookSection:
        key = (citation.runbook_id, citation.runbook_version, citation.section_id)
        try:
            return self._by_ref[key]
        except KeyError as exc:
            raise KeyError("runbook citation is not in the approved versioned catalogue") from exc

    @staticmethod
    def _parse(path: Path) -> list[RunbookSection]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0] != "---":
            raise ValueError(f"runbook {path.name} has no metadata header")
        try:
            end = lines.index("---", 1)
        except ValueError as exc:
            raise ValueError(f"runbook {path.name} metadata header is not closed") from exc
        metadata: dict[str, str] = {}
        for line in lines[1:end]:
            key, separator, value = line.partition(":")
            if not separator:
                raise ValueError(f"invalid runbook metadata line: {line}")
            metadata[key.strip()] = value.strip()
        required = {"runbook_id", "version", "title", "tags"}
        if not required <= metadata.keys():
            raise ValueError(f"runbook {path.name} is missing required metadata")
        document_tags = frozenset(tag.strip().lower() for tag in metadata["tags"].split(","))
        sections: list[RunbookSection] = []
        section_id: str | None = None
        section_title: str | None = None
        body: list[str] = []

        def flush() -> None:
            if section_id and section_title:
                excerpt = " ".join(line.strip() for line in body if line.strip())
                cautions = tuple(
                    line.removeprefix("CAUTION:").strip()
                    for line in body
                    if line.startswith("CAUTION:")
                )
                sections.append(
                    RunbookSection(
                        citation=RunbookCitationRef(
                            runbook_id=metadata["runbook_id"],
                            runbook_version=metadata["version"],
                            section_id=section_id,
                        ),
                        runbook_title=metadata["title"],
                        section_title=section_title,
                        approved_guidance_excerpt=excerpt[:1200],
                        tags=document_tags,
                        cautions=cautions,
                    )
                )

        for line in lines[end + 1 :]:
            if line.startswith("## "):
                flush()
                heading = line[3:].strip()
                section_id, separator, section_title = heading.partition(" — ")
                if not separator:
                    raise ValueError(f"runbook section must use 'section-id — Title': {heading}")
                body = []
            else:
                body.append(line)
        flush()
        return sections
