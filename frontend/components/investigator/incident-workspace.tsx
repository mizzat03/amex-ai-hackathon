"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, ClipboardCheck, FileCheck2, GitCommitHorizontal, ShieldAlert, Sparkles } from "lucide-react";
import { MetricChart } from "@/components/charts/metric-chart";
import { AppShell } from "@/components/investigator/app-shell";
import { CopilotThread } from "@/components/investigator/copilot-thread";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { evidenceFixture, metricHistoryFixture, workspaceFixture, type Api } from "@/data/fixtures/scenarios";
import { HttpInvestigatorRepository, InvestigatorApiError } from "@/data/repositories/http-investigator-repository";
import type { ConnectionState, InvestigatorRepository } from "@/data/repositories/investigator-repository";
import { createLiveSubscription, type LiveResource } from "@/data/repositories/live-updates";
import { runtimeRepository } from "@/data/repositories/runtime-repository";
import { cn, formatLocalDateTime, formatMetric, formatPercent, formatTime, formatUtcDateTime } from "@/lib/utils";

type IncidentTab = "summary" | "timeline" | "evidence" | "copilot" | "review";

function FactCard({ eyebrow, children, detail, tone = "neutral" }: { eyebrow: string; children: React.ReactNode; detail: React.ReactNode; tone?: "neutral" | "danger" | "positive" }): React.JSX.Element {
  return <Card className={cn("shadow-none", tone === "danger" && "border-[color-mix(in_srgb,var(--danger)_28%,var(--line))]", tone === "positive" && "border-[color-mix(in_srgb,var(--positive)_28%,var(--line))]")}><CardContent className="p-4"><p className="eyebrow">{eyebrow}</p><div className="mt-3 text-base font-extrabold leading-snug">{children}</div><div className="mt-2 text-xs leading-5 text-[var(--ink-muted)]">{detail}</div></CardContent></Card>;
}

function humanizeIdentifier(value: string): string {
  const words = value.trim().replaceAll("_", " ").replaceAll("-", " ").split(/\s+/);
  return words.map((word, index) => {
    if (/^[A-Z]{2,3}$/.test(word)) return word;
    const lower = word.toLowerCase();
    if (lower === "api" || lower === "rca") return lower.toUpperCase();
    return index === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
  }).join(" ");
}

function candidateTypeLabel(candidateType: Api["HypothesisView"]["candidate_type"]): string {
  return {
    DEPLOYMENT: "Deployment",
    CONFIG_CHANGE: "Configuration change",
    ROLLBACK: "Rollback",
  }[candidateType];
}

function evidenceTierLabel(tier: Api["EvidenceTier"]): string {
  return humanizeIdentifier(tier).replace(/ evidence$/i, "");
}

function scopeDisplayLabel(scope: Api["AffectedScopeView"] | null): string {
  if (!scope) return "Scope not yet established";
  const primary = scope.scope.payment_method
    ? humanizeIdentifier(scope.scope.payment_method)
    : scope.scope.service
      ? humanizeIdentifier(scope.scope.service)
      : humanizeIdentifier(scope.label);
  return [primary, scope.scope.service_version].filter(Boolean).join(" · ");
}

function IncidentSummarySection({ workspace }: { workspace: Api["IncidentWorkspaceResponse"] }): React.JSX.Element {
  const scope = workspace.affected_scope;
  const signature = workspace.error_signature;
  const leading = workspace.rca_summary.leading_hypothesis;
  const alternatives = workspace.rca_summary.alternatives ?? [];
  const causeLabel = leading ? candidateTypeLabel(leading.candidate_type) : "Not established";
  const supportingCount = leading?.relations.filter((relation) => relation.relation === "SUPPORTING").length ?? 0;
  const challengingCount = leading?.relations.filter((relation) => relation.relation === "CONTRADICTORY").length ?? 0;

  return <>
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <FactCard eyebrow="Lifecycle" detail={<>Started <time dateTime={workspace.incident.started_at} title={formatUtcDateTime(workspace.incident.started_at)}>{formatLocalDateTime(workspace.incident.started_at)} local</time><br />Updated {formatTime(workspace.incident.updated_at)} local</>} tone={workspace.incident.lifecycle === "RESOLVED" ? "positive" : "danger"}>{humanizeIdentifier(workspace.incident.lifecycle)}</FactCard>
      <FactCard eyebrow="Affected scope" detail={<>{scope ? <>{scope.scope.processing_region ? `${scope.scope.processing_region} · ` : ""}{formatPercent(scope.traffic_share.value)} traffic share · {formatMetric(scope.excess_technical_errors.value, scope.excess_technical_errors.unit)} excess errors</> : "No scope passed the configured gates."}</>}>{scopeDisplayLabel(scope)}</FactCard>
      <FactCard eyebrow="Observed failure" detail={<>{signature ? `${formatPercent(signature.share_of_technical_errors.value)} of technical errors · ${formatMetric(signature.excess_count.value, signature.excess_count.unit)} excess occurrences` : "No dominant signature available."}</>} tone={signature ? "danger" : "neutral"}>{signature ? humanizeIdentifier(signature.normalized_error_code) : "Not established"}</FactCard>
      <FactCard eyebrow="Likely cause" detail={<>{leading ? `${evidenceTierLabel(leading.evidence_tier)} evidence · ${leading.relations.length} evidence links` : workspace.rca_summary.insufficient_evidence_reason}</>} tone={leading ? "positive" : "neutral"}>{causeLabel}</FactCard>
    </div>
    <Card className="mt-6">
      <CardContent className="grid gap-7 p-6 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,.55fr)]">
        <section aria-labelledby="leading-cause-heading">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={leading ? "positive" : "warning"}>{evidenceTierLabel(workspace.rca_summary.overall_tier)} evidence</Badge>
            <span className="text-xs text-[var(--ink-muted)]">Deterministic RCA · result version {workspace.rca_summary.result_version}</span>
          </div>
          <h2 id="leading-cause-heading" className="mt-4 text-2xl font-extrabold">{leading ? `${causeLabel} is the leading explanation` : "No leading explanation yet"}</h2>
          {leading ? <>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--ink-soft)]">This candidate ranks highest from observed timing, scope, and error evidence. It is not a claim of proven causality.</p>
            <dl className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-[var(--surface-muted)] p-4"><dt className="eyebrow">Affected traffic</dt><dd className="mt-2 text-sm font-bold leading-5">{scopeDisplayLabel(scope)}</dd></div>
              <div className="rounded-xl bg-[var(--surface-muted)] p-4"><dt className="eyebrow">Observed failure</dt><dd className="mt-2 text-sm font-bold leading-5">{signature ? humanizeIdentifier(signature.normalized_error_code) : "Not established"}</dd></div>
              <div className="rounded-xl bg-[var(--surface-muted)] p-4"><dt className="eyebrow">Evidence links</dt><dd className="mt-2 text-sm font-bold leading-5">{supportingCount} supporting{challengingCount ? ` · ${challengingCount} challenging` : ""}</dd></div>
            </dl>
            <details className="mt-4 rounded-xl border border-[var(--line)] px-4 py-3 text-sm">
              <summary className="cursor-pointer font-bold text-[var(--ink-soft)]">Show technical hypothesis</summary>
              <p className="mt-3 leading-6 text-[var(--ink-muted)]">{leading.summary}</p>
            </details>
          </> : <p className="mt-3 text-sm leading-6 text-[var(--ink-soft)]">{workspace.rca_summary.insufficient_evidence_reason}</p>}
        </section>
        <div className="space-y-3">{alternatives.map((alternative) => <div key={alternative.hypothesis_id} className="rounded-xl border border-[var(--line)] p-4"><p className="eyebrow">Alternative · {candidateTypeLabel(alternative.candidate_type)}</p><p className="mt-3 text-sm font-bold leading-6">{alternative.summary}</p><Badge tone="warning" className="mt-3">{evidenceTierLabel(alternative.evidence_tier)} evidence</Badge></div>)}</div>
      </CardContent>
    </Card>
  </>;
}

function TimelineRail({ items }: { items: Api["IncidentTimelineItem"][] }): React.JSX.Element {
  return <ol aria-label="Incident event timeline" className="relative space-y-6 before:absolute before:bottom-2 before:left-[.45rem] before:top-2 before:w-px before:bg-[var(--line)]">{items.map((item) => <li key={item.timeline_item_id} className="relative grid grid-cols-[1rem_1fr] gap-3"><span className={cn("relative z-10 mt-1 size-3 rounded-full border-2 border-[var(--surface)]", item.lifecycle === "OPEN" ? "bg-[var(--danger)]" : item.event_type === "RECOVERY" || item.lifecycle === "RESOLVED" ? "bg-[var(--positive)]" : "bg-[var(--ink-muted)]")} /><div><time dateTime={item.occurred_at} title={formatUtcDateTime(item.occurred_at)} className="mono text-[10px] font-bold text-[var(--ink-muted)]">{formatTime(item.occurred_at)} local</time><p className="mt-1 text-sm font-bold">{item.title}</p><p className="mt-1 text-xs leading-5 text-[var(--ink-muted)]">{item.summary}</p></div></li>)}</ol>;
}

function EvidenceSection({ evidence }: { evidence: Api["EvidenceProjectionResponse"] }): React.JSX.Element {
  const groups = [
    { title: "Observed facts", icon: FileCheck2, tone: "info" as const, items: evidence.items.filter((item) => item.category === "OBSERVED_FACT") },
    { title: "Deterministic findings", icon: GitCommitHorizontal, tone: "positive" as const, items: evidence.items.filter((item) => item.category === "DERIVED_FINDING") },
    { title: "Limitations & missing evidence", icon: ShieldAlert, tone: "warning" as const, items: evidence.items.filter((item) => item.category === "LIMITATION" || item.category === "MISSING_EVIDENCE") },
  ];
  return <section aria-labelledby="evidence-heading"><div className="mb-4"><p className="eyebrow">Evidence package · v{evidence.evidence_package_version}</p><h2 id="evidence-heading" className="mt-2 text-2xl font-extrabold tracking-tight">What is known, derived, and missing</h2></div><div className="grid gap-4 xl:grid-cols-3">{groups.map((group) => { const Icon = group.icon; return <Card key={group.title} className="shadow-none"><CardHeader><div className="flex items-center gap-2"><Icon aria-hidden="true" className="size-4 text-[var(--accent)]" /><h3 className="font-bold">{group.title}</h3></div><Badge tone={group.tone}>{group.items.length}</Badge></CardHeader><CardContent><Accordion type="multiple">{group.items.map((item) => <AccordionItem key={item.evidence_id} value={item.evidence_id}><AccordionTrigger><span><span className="mono block text-[10px] text-[var(--ink-muted)]">{item.evidence_id}</span><span className="mt-1 block pr-4 leading-5">{item.statement}</span></span></AccordionTrigger><AccordionContent><p><strong>Provenance:</strong> {item.provenance_label}</p><p className="mt-1"><strong>Source:</strong> {item.source_module} · {item.source_version}</p><p className="mt-1"><strong>Temporal scope:</strong> {item.temporal_scope.replaceAll("_", " ").toLowerCase()}</p></AccordionContent></AccordionItem>)}</Accordion>{group.items.length === 0 ? <p className="text-sm text-[var(--ink-muted)]">No items in this group.</p> : null}</CardContent></Card>; })}</div></section>;
}

function incidentListReturnUrl(): "/incidents" | `/incidents?${string}` {
  if (typeof window === "undefined") return "/incidents";
  const candidate = new URLSearchParams(window.location.search).get("return_to");
  if (candidate === "/incidents") return candidate;
  return candidate?.startsWith("/incidents?") ? candidate as `/incidents?${string}` : "/incidents";
}

function reviewedReturnUrl(incidentId: string): string {
  const url = new URL(incidentListReturnUrl(), window.location.origin);
  url.searchParams.set("reviewed", incidentId);
  return `${url.pathname}${url.search}`;
}

function ReviewSection({ repository, workspace, onSaved, onConflict, navigate }: { repository: InvestigatorRepository; workspace: Api["IncidentWorkspaceResponse"]; onSaved: (review: Api["HumanReviewView"]) => void; onConflict: () => Promise<void>; navigate: (url: string) => void }): React.JSX.Element {
  const [status, setStatus] = React.useState<Api["HumanReviewRequest"]["status"]>("ACKNOWLEDGED");
  const [note, setNote] = React.useState(""); const [error, setError] = React.useState(""); const [notice, setNotice] = React.useState(""); const [busy, setBusy] = React.useState(false);
  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (status !== "ACKNOWLEDGED" && note.trim().length < 12) { setError("Add at least 12 characters explaining this review decision."); return; }
    setBusy(true);
    try {
      const result = await repository.updateHumanReview(workspace.incident_id, { hypothesis_id: workspace.rca_summary.leading_hypothesis?.hypothesis_id ?? "UNAVAILABLE", status, note: note.trim() || null, expected_version: workspace.human_review.version });
      onSaved(result); setError(""); const confirmation = `Review saved as ${result.status.toLowerCase()} version ${result.version}. Returning to incidents.`; setNotice(confirmation); sessionStorage.setItem("amex:review-success", confirmation); navigate(reviewedReturnUrl(workspace.incident_id));
    } catch (cause) {
      setNotice(""); setError(cause instanceof Error ? cause.message : "The review could not be saved."); if (cause instanceof InvestigatorApiError && cause.code === "VERSION_CONFLICT") await onConflict();
    } finally { setBusy(false); }
  }
  return <section aria-labelledby="review-heading"><Card><CardContent className="grid gap-6 p-6 lg:grid-cols-[1fr_1.1fr]"><div><p className="eyebrow">Human review</p><h2 id="review-heading" className="mt-2 text-2xl font-extrabold">Record an accountable decision</h2><p className="mt-3 max-w-xl text-sm leading-6 text-[var(--ink-soft)]">Review applies to the leading deterministic hypothesis and optimistic version {workspace.human_review.version}. No remediation is performed by this action.</p></div><form onSubmit={submit} noValidate><div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="review-status" className="text-xs font-bold">Decision</label><select id="review-status" value={status} onChange={(event) => setStatus(event.target.value as typeof status)} className="mt-2 min-h-10 w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"><option value="ACKNOWLEDGED">Acknowledge</option><option value="REJECTED">Reject</option><option value="INCONCLUSIVE">Inconclusive</option></select></div><div><label htmlFor="review-note" className="text-xs font-bold">Review note {status !== "ACKNOWLEDGED" ? "(required)" : "(optional)"}</label><input id="review-note" value={note} onChange={(event) => setNote(event.target.value)} aria-invalid={Boolean(error)} aria-describedby="review-message" className="mt-2 min-h-10 w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]" placeholder="Explain the evidence decision" /></div></div><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p id="review-message" role={error ? "alert" : "status"} className={cn("text-xs", error ? "text-[var(--danger)]" : "text-[var(--positive)]")}>{error || notice || `Current review: ${workspace.human_review.status.toLowerCase()} · version ${workspace.human_review.version}`}</p><Button disabled={busy || !workspace.rca_summary.leading_hypothesis}><ClipboardCheck aria-hidden="true" className="size-4" />Save review</Button></div></form></CardContent></Card></section>;
}

export function IncidentWorkspace({ incidentId = workspaceFixture.incident_id, repository = runtimeRepository, navigate = (url) => window.location.assign(url) }: { incidentId?: string; repository?: InvestigatorRepository; navigate?: (url: string) => void } = {}): React.JSX.Element {
  const live = repository instanceof HttpInvestigatorRepository;
  const [workspace, setWorkspace] = React.useState<Api["IncidentWorkspaceResponse"] | null>(live ? null : workspaceFixture);
  const [evidence, setEvidence] = React.useState<Api["EvidenceProjectionResponse"] | null>(live ? null : evidenceFixture);
  const [history, setHistory] = React.useState<Api["MetricHistoryResponse"] | null>(live ? null : metricHistoryFixture);
  const [connection, setConnection] = React.useState<ConnectionState>({ status: "disconnected", lastSequence: 0 });
  const [loadError, setLoadError] = React.useState(""); const [activeTab, setActiveTab] = React.useState<IncidentTab>("summary");
  const copilotTrigger = React.useRef<HTMLButtonElement>(null);

  const refresh = React.useCallback(async (resource: LiveResource = "all") => {
    try {
      const jobs: Promise<void>[] = [];
      if (resource === "all" || resource === "incidents" || resource === "review") jobs.push(repository.getIncident(incidentId).then(setWorkspace));
      if (resource === "all" || resource === "evidence") jobs.push(repository.getEvidence(incidentId).then(setEvidence));
      if (resource === "all" || resource === "incidents") { const end = new Date(); const start = new Date(end.getTime() - 35 * 60_000); jobs.push(repository.getMetricHistory({ metricKey: "technical_error_rate", startAt: start.toISOString(), endAt: end.toISOString(), incidentId }).then(setHistory)); }
      await Promise.all(jobs); setLoadError("");
    } catch (cause) { setLoadError(cause instanceof Error ? cause.message : "Incident data could not be refreshed."); }
  }, [incidentId, repository]);

  React.useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer); }, [refresh]);
  React.useEffect(() => { if (!(repository instanceof HttpInvestigatorRepository)) return; const subscription = createLiveSubscription({ apiBaseUrl: repository.baseUrl, onInvalidate: (event) => void refresh(event.resource), onState: setConnection }); return () => subscription.close(); }, [refresh, repository]);

  if (!workspace || !evidence || !history) return <AppShell mode="investigation" active="Incidents"><main className="mx-auto max-w-[1500px] px-5 py-16"><div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-10 text-center" aria-live="polite"><p className="font-bold">{loadError ? "Incident unavailable" : "Loading live investigation…"}</p><p className="mt-2 text-sm text-[var(--ink-muted)]">{loadError || "Verified incident data will appear when the request completes."}</p>{loadError ? <Button className="mt-4" variant="secondary" onClick={() => void refresh()}>Retry</Button> : null}</div></main></AppShell>;

  const signature = workspace.error_signature;
  const currentMetric = history.points.at(-1)?.value ?? null;
  const baselineRate = signature?.attempt_rate.comparison?.baseline_value ?? 0;
  function openCopilot(): void { setActiveTab("copilot"); window.setTimeout(() => copilotTrigger.current?.focus(), 0); }

  return <AppShell mode="investigation" active="Incidents">
    <main className="mx-auto max-w-[1500px] px-5 py-7 sm:px-7 lg:px-9">
      <p aria-live="polite" className="sr-only">{loadError || `Data connection ${connection.status}; last sequence ${connection.lastSequence}`}</p>
      <Link href={incidentListReturnUrl()} className="inline-flex items-center gap-2 rounded-lg text-xs font-bold text-[var(--ink-muted)] outline-none hover:text-[var(--ink)] focus-visible:ring-2 focus-visible:ring-[var(--focus)]"><ArrowLeft aria-hidden="true" className="size-3.5" />All incidents</Link>
      <header className="mt-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={workspace.incident.lifecycle === "RESOLVED" ? "positive" : "danger"}>{workspace.incident.lifecycle.replaceAll("_", " ").toLowerCase()}</Badge>
          <Badge tone="danger">{workspace.incident.severity.toLowerCase()} severity</Badge>
          <Badge tone={workspace.evidence_status.completeness === "COMPLETE" ? "positive" : "warning"}>Evidence {workspace.evidence_status.completeness.toLowerCase()}</Badge>
          <span className="mono text-xs text-[var(--ink-muted)]">{workspace.incident_id}</span>
        </div>
        <div className="mt-4 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
          <div><h1 className="max-w-4xl text-3xl font-black leading-tight tracking-[-.035em] sm:text-4xl">{workspace.incident.title}</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--ink-soft)]">{workspace.incident.impact_summary}</p></div>
          <Button onClick={openCopilot}><Sparkles aria-hidden="true" className="size-4" />Open Copilot</Button>
        </div>
      </header>
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as IncidentTab)} className="mt-6">
        <TabsList aria-label="Incident workspace" className="sticky top-14 z-30 flex w-full justify-start gap-1 overflow-x-auto rounded-none border-x-0 bg-[color-mix(in_srgb,var(--canvas)_92%,transparent)] px-1 py-2 backdrop-blur-xl lg:top-0 lg:rounded-xl lg:border-x">
          <TabsTrigger value="summary">Summary</TabsTrigger><TabsTrigger value="timeline">Timeline</TabsTrigger><TabsTrigger value="evidence">Evidence</TabsTrigger><TabsTrigger ref={copilotTrigger} value="copilot">Copilot</TabsTrigger><TabsTrigger value="review">Review</TabsTrigger>
        </TabsList>
        <TabsContent value="summary" className="pt-6"><IncidentSummarySection workspace={workspace} /></TabsContent>
        <TabsContent value="timeline" className="pt-6"><div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">Shared time axis</p><h2 className="mt-2 text-2xl font-extrabold tracking-tight">Signal and operational events</h2></div><p className="text-xs text-[var(--ink-muted)]">Current {formatTime(workspace.incident.current_period.start_at)}–{formatTime(workspace.incident.current_period.end_at)} · baseline {formatTime(workspace.incident.baseline_period.start_at)}–{formatTime(workspace.incident.baseline_period.end_at)} local</p></div><Card><CardContent className="grid gap-7 p-5 xl:grid-cols-[minmax(0,1fr)_16rem]"><div><div className="mb-3"><p className="eyebrow">Technical error rate</p><p className="metric-number mt-1 text-3xl font-extrabold">{formatPercent(currentMetric)}</p></div>{history.points.length ? <MetricChart points={history.points} baseline={baselineRate} mode="rate" compact /> : <p className="rounded-xl border border-dashed border-[var(--line)] p-8 text-sm text-[var(--ink-muted)]">No metric history is available for this incident window.</p>}</div><aside className="border-t border-[var(--line)] pt-5 xl:border-l xl:border-t-0 xl:pl-6 xl:pt-0"><p className="eyebrow mb-5">Event rail</p><TimelineRail items={workspace.timeline} /></aside></CardContent></Card></TabsContent>
        <TabsContent value="evidence" className="pt-6"><EvidenceSection evidence={evidence} /></TabsContent>
        <TabsContent value="copilot" className="pt-6"><CopilotThread incidentId={workspace.incident_id} repository={repository} /></TabsContent>
        <TabsContent value="review" className="pt-6"><ReviewSection repository={repository} workspace={workspace} onSaved={(review) => setWorkspace((value) => value ? { ...value, human_review: review, incident: { ...value.incident, human_review_status: review.status, updated_at: review.updated_at } } : value)} onConflict={() => refresh("review")} navigate={navigate} /></TabsContent>
      </Tabs>
      <footer className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--line)] py-5 text-xs text-[var(--ink-muted)]"><span>Evidence package {evidence.evidence_package_id} · v{evidence.evidence_package_version} · {evidence.completeness.toLowerCase()}</span><time dateTime={workspace.generated_at} title={formatUtcDateTime(workspace.generated_at)}>Generated {formatLocalDateTime(workspace.generated_at)} local · human review {workspace.human_review.status.toLowerCase()}</time></footer>
    </main>
  </AppShell>;
}
