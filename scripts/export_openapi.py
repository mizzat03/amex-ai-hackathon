"""Export the deterministic OpenAPI contract consumed by the frontend generator."""

import json
from pathlib import Path

from backend.api.app import app
from backend.evidence.builder import EvidencePackage


def main() -> None:
    target = Path("backend/contracts/openapi.v1.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {target}")
    evidence_target = Path("backend/contracts/evidence-package.v1.schema.json")
    evidence_target.write_text(
        json.dumps(EvidencePackage.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {evidence_target}")


if __name__ == "__main__":
    main()
