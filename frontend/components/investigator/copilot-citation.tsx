"use client";

import type { components } from "@/generated/api-types";
import { formatLocalDateTime } from "@/lib/utils";

type Api = components["schemas"];

function readableValue(value: Record<string, unknown> | null | undefined, unit: string | null | undefined): string {
  if (!value) return "No structured value supplied";
  const entries = Object.entries(value).map(([key, item]) => `${key.replaceAll("_", " ")}: ${String(item)}`);
  return `${entries.join("; ")}${unit ? ` (${unit.toLowerCase()})` : ""}`;
}

function scopeLabel(scope: Api["ScopedValue"] | null | undefined): string {
  if (!scope) return "Incident-wide";
  return Object.values(scope).filter(Boolean).join(" · ") || "Incident-wide";
}

export function CopilotCitation({ citation }: { citation: Api["CopilotEvidenceCitation"] | Api["CopilotRunbookCitation"] }): React.JSX.Element {
  if (citation.citation_type === "RUNBOOK") {
    return (
      <details className="copilot-citation">
        <summary aria-label={`Open citation ${citation.citation_number}`}>[{citation.citation_number}]</summary>
        <div className="copilot-citation-body">
          <p className="font-bold">{citation.title}</p>
          <p className="mt-2 text-sm leading-6">{citation.approved_guidance_excerpt}</p>
          <p className="mt-2 text-xs text-[var(--ink-muted)]">Approved guidance, not incident proof.</p>
          <details className="mt-3">
            <summary className="text-xs font-bold text-[var(--ink-muted)]">Technical details</summary>
            <dl className="mt-2 grid gap-1 text-xs"><dt>Runbook</dt><dd className="mono">{citation.runbook_id}</dd><dt>Version and section</dt><dd className="mono">{citation.runbook_version} · {citation.section_id}</dd></dl>
          </details>
        </div>
      </details>
    );
  }

  return (
    <details className="copilot-citation">
      <summary aria-label={`Open citation ${citation.citation_number}`}>[{citation.citation_number}]</summary>
      <div className="copilot-citation-body">
        <p className="font-bold leading-6">{citation.statement}</p>
        <dl className="mt-3 grid gap-x-4 gap-y-2 text-xs sm:grid-cols-[8rem_1fr]">
          <dt>Value</dt><dd>{readableValue(citation.structured_value, citation.unit)}</dd>
          <dt>Scope</dt><dd>{scopeLabel(citation.scope)}</dd>
          <dt>Time window</dt><dd>{citation.period ? `${formatLocalDateTime(citation.period.start_at)}–${formatLocalDateTime(citation.period.end_at)} local` : "Snapshot"}</dd>
          <dt>Provenance</dt><dd>{citation.provenance_label}</dd>
          <dt>Evidence version</dt><dd>Version {citation.evidence_package_version}</dd>
        </dl>
        <details className="mt-3 border-t border-[var(--line)] pt-3">
          <summary className="text-xs font-bold text-[var(--ink-muted)]">Technical details</summary>
          <dl className="mt-2 grid gap-1 text-xs">
            <dt>Evidence ID</dt><dd className="mono">{citation.technical_details.evidence_id ?? "Unavailable"}</dd>
            <dt>Source</dt><dd className="mono">{citation.technical_details.source_module ?? "Unavailable"} · {citation.technical_details.source_version ?? "Unavailable"}</dd>
            {citation.technical_details.calculation_method ? <><dt>Calculation</dt><dd>{citation.technical_details.calculation_method}</dd></> : null}
            {citation.technical_details.calculation_lineage?.length ? <><dt>Lineage</dt><dd>{citation.technical_details.calculation_lineage.join(" → ")}</dd></> : null}
          </dl>
        </details>
      </div>
    </details>
  );
}
