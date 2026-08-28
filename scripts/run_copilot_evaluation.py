"""Run the locked two-provider evaluation without accepting or printing secret values."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from backend.copilot.evaluation import load_cases, run_candidate
from backend.copilot.provider import AnthropicMessagesProvider, OpenAIResponsesProvider


REQUIRED_ENVIRONMENT = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AMEX_EVAL_CLAUDE_MODEL",
    "AMEX_EVAL_TERRA_MODEL",
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/model-evaluation-results.json"),
        help="Blinded validated-output artifact; never contains provider credentials.",
    )
    parser.add_argument(
        "--mapping-output",
        type=Path,
        default=Path("docs/model-evaluation-candidate-map.json"),
        help="Candidate/provider mapping kept separate from blind review.",
    )
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 6))
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    missing = [name for name in REQUIRED_ENVIRONMENT if not os.environ.get(name)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if missing:
        pending = {
            "status": "PENDING_CREDENTIALS",
            "generated_at": datetime.now(UTC).isoformat(),
            "winner": None,
            "missing_environment_variables": missing,
            "case_count": len(load_cases()),
            "note": "No provider calls were made and no winner was inferred.",
        }
        args.output.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")
        print("Copilot evaluation is pending; required environment variables are not configured.")
        print("No provider calls were made and no winner was selected.")
        return 2

    claude = AnthropicMessagesProvider(
        model_id=os.environ["AMEX_EVAL_CLAUDE_MODEL"],
        api_key=os.environ["ANTHROPIC_API_KEY"],
        endpoint="https://api.anthropic.com/v1/messages",
        timeout_seconds=30,
    )
    terra = OpenAIResponsesProvider(
        model_id=os.environ["AMEX_EVAL_TERRA_MODEL"],
        api_key=os.environ["OPENAI_API_KEY"],
        endpoint="https://api.openai.com/v1/responses",
        timeout_seconds=30,
    )
    candidates = {"candidate_a": claude, "candidate_b": terra}
    blinded: dict[str, object] = {
        "status": "AWAITING_BLIND_RUBRIC",
        "generated_at": datetime.now(UTC).isoformat(),
        "winner": None,
        "repetitions": args.repetitions,
        "candidates": {},
    }
    for candidate_name, provider in candidates.items():
        runs = []
        for _ in range(args.repetitions):
            artifact = await run_candidate(provider)
            artifact.pop("provider", None)
            artifact.pop("model_id", None)
            runs.append(artifact)
        blinded["candidates"][candidate_name] = runs  # type: ignore[index]
    args.output.write_text(json.dumps(blinded, indent=2) + "\n", encoding="utf-8")
    args.mapping_output.write_text(
        json.dumps(
            {
                "candidate_a": {"provider": claude.provider_name, "model_id": claude.model_id},
                "candidate_b": {"provider": terra.provider_name, "model_id": terra.model_id},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Provider runs completed. Blind rubric scoring is required before selecting a winner.")
    return 0


def main() -> int:
    return asyncio.run(run(arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
