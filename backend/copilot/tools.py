"""Allowlisted, bounded, incident-scoped read-only domain tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Awaitable, Callable

from backend.copilot.models import CopilotContext


class ToolAuthorizationError(ValueError):
    pass


ReadOnlyTool = Callable[[CopilotContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ToolResult:
    evidence_id: str
    tool_name: str
    arguments: dict[str, Any]
    occurred_at: datetime
    temporal_scope: str
    payload: dict[str, Any]


class ReadOnlyToolRegistry:
    TOOLSET_VERSION = "copilot-read-tools.v1"
    ALLOWED_NAMES = frozenset(
        {
            "get_incident_overview",
            "get_metric_breakdown",
            "get_metric_timeseries",
            "get_operational_changes",
            "get_hypothesis_evidence",
            "get_evidence_item",
            "search_runbooks",
        }
    )

    def __init__(self, tools: dict[str, ReadOnlyTool], *, max_calls: int = 4) -> None:
        unknown = set(tools) - self.ALLOWED_NAMES
        if unknown:
            raise ValueError(f"Unapproved tools configured: {sorted(unknown)}")
        if not 1 <= max_calls <= 8:
            raise ValueError("tool-call budget must be between 1 and 8")
        self._tools = dict(tools)
        self._max_calls = max_calls

    def definitions(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "name": name,
                "description": "Read-only, incident-scoped investigator data lookup.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "incident_id": {"type": "string"},
                        "evidence_id": {"type": "string"},
                        "hypothesis_id": {"type": "string"},
                    },
                    "required": ["incident_id"],
                    "additionalProperties": False,
                },
            }
            for name in sorted(self._tools)
        )

    async def execute_many(
        self,
        context: CopilotContext,
        calls: list[tuple[str, dict[str, Any]]],
    ) -> list[ToolResult]:
        if len(calls) > self._max_calls:
            raise ToolAuthorizationError("tool-call budget exceeded")
        seen: set[tuple[str, str]] = set()
        results: list[ToolResult] = []
        for name, arguments in calls:
            if name not in self.ALLOWED_NAMES or name not in self._tools:
                raise ToolAuthorizationError("tool is not available in the approved read-only set")
            if arguments.get("incident_id") != context.incident_id:
                raise ToolAuthorizationError("tool request is outside the active incident")
            signature = (name, repr(sorted(arguments.items())))
            if signature in seen:
                raise ToolAuthorizationError("duplicate tool call rejected")
            seen.add(signature)
            if any(key in arguments for key in ("sql", "command", "write", "mutation")):
                raise ToolAuthorizationError("write-capable arguments are prohibited")
            payload = await self._tools[name](context, arguments)
            if len(repr(payload)) > 24_000:
                raise ToolAuthorizationError("tool result exceeded the bounded context limit")
            results.append(
                ToolResult(
                    evidence_id=f"EV-TOOL-{sha256(f'{context.interaction_id}:{name}:{signature[1]}'.encode()).hexdigest()[:12].upper()}",
                    tool_name=name,
                    arguments=arguments,
                    occurred_at=datetime.now(UTC),
                    temporal_scope=str(payload.get("temporal_scope", "INCIDENT_SNAPSHOT")),
                    payload=payload,
                )
            )
        return results


def projection_tools() -> ReadOnlyToolRegistry:
    async def incident_overview(context: CopilotContext, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        return {
            "incident_id": context.incident_id,
            "leading_hypothesis_id": context.leading_hypothesis_id,
            "evidence_tier": context.evidence_tier.value,
            "temporal_scope": "INCIDENT_SNAPSHOT",
        }

    async def evidence_item(context: CopilotContext, arguments: dict[str, Any]) -> dict[str, Any]:
        evidence_id = arguments.get("evidence_id")
        item = next((item for item in context.evidence_items if item.get("evidence_id") == evidence_id), None)
        if item is None:
            raise ToolAuthorizationError("evidence item is not in the pinned package")
        return {**item, "temporal_scope": item.get("temporal_scope", "INCIDENT_SNAPSHOT")}

    async def hypothesis_evidence(context: CopilotContext, arguments: dict[str, Any]) -> dict[str, Any]:
        hypothesis_id = arguments.get("hypothesis_id")
        if hypothesis_id not in {context.leading_hypothesis_id, context.strongest_alternative_id}:
            raise ToolAuthorizationError("hypothesis is not in the pinned context")
        return {
            "hypothesis_id": hypothesis_id,
            "evidence": context.evidence_items,
            "temporal_scope": "INCIDENT_SNAPSHOT",
        }

    async def runbook_search(context: CopilotContext, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        return {
            "sections": context.runbook_sections[:3],
            "temporal_scope": "INCIDENT_SNAPSHOT",
            "guidance_not_incident_proof": True,
        }

    async def unavailable_detail(context: CopilotContext, arguments: dict[str, Any]) -> dict[str, Any]:
        del context, arguments
        return {
            "available": False,
            "limitation": "The bounded pinned projection does not contain this detail.",
            "temporal_scope": "INCIDENT_SNAPSHOT",
        }

    return ReadOnlyToolRegistry(
        {
            "get_incident_overview": incident_overview,
            "get_metric_breakdown": unavailable_detail,
            "get_metric_timeseries": unavailable_detail,
            "get_operational_changes": unavailable_detail,
            "get_hypothesis_evidence": hypothesis_evidence,
            "get_evidence_item": evidence_item,
            "search_runbooks": runbook_search,
        }
    )
