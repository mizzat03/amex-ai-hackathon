"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpDown, Filter, Search } from "lucide-react";
import { AppShell } from "@/components/investigator/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Api } from "@/data/fixtures/scenarios";
import { HttpInvestigatorRepository } from "@/data/repositories/http-investigator-repository";
import type { InvestigatorRepository } from "@/data/repositories/investigator-repository";
import { createLiveSubscription } from "@/data/repositories/live-updates";
import { runtimeRepository } from "@/data/repositories/runtime-repository";
import { cn, formatLocalDateTime, formatUtcDateTime } from "@/lib/utils";

function severityTone(severity: Api["IncidentSeverity"]): "danger" | "warning" | "neutral" {
  return severity === "HIGH" ? "danger" : severity === "MEDIUM" ? "warning" : "neutral";
}

export function IncidentsPage({ repository = runtimeRepository }: { repository?: InvestigatorRepository } = {}): React.JSX.Element {
  const initial = typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
  const [sourceItems, setSourceItems] = React.useState<Api["IncidentSummary"][]>([]);
  const [loaded, setLoaded] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");
  const [query, setQuery] = React.useState(initial.get("q") ?? "");
  const [severity, setSeverity] = React.useState<"ALL" | Api["IncidentSeverity"]>((initial.get("severity") as Api["IncidentSeverity"] | null) ?? "ALL");
  const [ascending, setAscending] = React.useState(initial.get("sort") === "asc");
  const [reviewNotice] = React.useState(() => { if (typeof window === "undefined") return ""; const notice = sessionStorage.getItem("amex:review-success") ?? ""; if (notice) sessionStorage.removeItem("amex:review-success"); return notice; });
  const reviewedId = initial.get("reviewed");

  const refresh = React.useCallback(async () => {
    try {
      const page = await repository.listIncidents({ sortBy: "started_at", sortDirection: ascending ? "asc" : "desc", ...(severity === "ALL" ? {} : { severity: [severity] }) });
      setSourceItems(page.items); setLoadError(""); setLoaded(true);
    } catch (cause) { setLoadError(cause instanceof Error ? cause.message : "Incidents could not be refreshed."); setLoaded(true); }
  }, [ascending, repository, severity, setLoadError, setLoaded, setSourceItems]);

  React.useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer); }, [refresh]);
  React.useEffect(() => { if (!(repository instanceof HttpInvestigatorRepository)) return; const subscription = createLiveSubscription({ apiBaseUrl: repository.baseUrl, onInvalidate: (event) => { if (event.resource === "incidents" || event.resource === "all" || event.resource === "review") void refresh(); }, onState: () => undefined }); return () => subscription.close(); }, [refresh, repository]);
  React.useEffect(() => { const search = new URLSearchParams(window.location.search); if (query) search.set("q", query); else search.delete("q"); if (severity === "ALL") search.delete("severity"); else search.set("severity", severity); search.set("sort", ascending ? "asc" : "desc"); window.history.replaceState(null, "", `${window.location.pathname}?${search.toString()}`); }, [ascending, query, severity]);
  React.useEffect(() => { if (!loaded) return; const position = Number(sessionStorage.getItem("amex:incidents-scroll")); if (Number.isFinite(position) && position > 0) window.scrollTo({ top: position }); }, [loaded]);

  const items = sourceItems.filter((item) => `${item.incident_id} ${item.title} ${item.dominant_error_signature ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  function clearFilters(): void { setQuery(""); setSeverity("ALL"); }

  return <AppShell active="Incidents"><div className="mx-auto max-w-[1500px] px-5 py-8 sm:px-7 lg:px-9"><header><p className="eyebrow">Incident archive</p><h1 className="mt-2 text-4xl font-black tracking-[-.04em]">Investigations</h1><p className="mt-3 text-sm text-[var(--ink-soft)]">Search, filter, and sort measured synthetic incidents by operational relevance.</p></header><p role="status" aria-live="polite" className="mt-4 text-sm font-semibold text-[var(--positive)]">{reviewNotice}</p><Card className="mt-4 shadow-none"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row"><label className="relative flex-1"><span className="sr-only">Search incidents</span><Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--ink-muted)]" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search incident ID, title, or signature" className="min-h-11 w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] pl-10 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]" /></label><label className="relative"><span className="sr-only">Filter severity</span><Filter aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--ink-muted)]" /><select value={severity} onChange={(event) => setSeverity(event.target.value as typeof severity)} className="min-h-11 rounded-xl border border-[var(--line)] bg-[var(--surface)] pl-10 pr-8 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"><option value="ALL">All severities</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option></select></label><Button variant="secondary" onClick={() => setAscending((value) => !value)}><ArrowUpDown aria-hidden="true" className="size-4" />Started {ascending ? "oldest" : "newest"}</Button></CardContent></Card><div className="mt-5 overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)]"><div className="overflow-x-auto"><table className="w-full min-w-[960px] border-collapse text-left"><caption className="sr-only">Incident investigations</caption><thead><tr className="border-b border-[var(--line)] bg-[var(--surface-muted)] text-[10px] font-extrabold uppercase tracking-[.12em] text-[var(--ink-muted)]"><th className="px-5 py-3">Incident</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Scope</th><th className="px-4 py-3">Signature</th><th className="px-4 py-3">Evidence</th><th className="px-4 py-3">Started</th></tr></thead><tbody>{items.map((item) => { const returnTo = `${window.location.pathname}${window.location.search}`; return <tr id={`incident-${item.incident_id}`} key={item.incident_id} className={cn("border-b border-[var(--line)] last:border-0 hover:bg-[var(--surface-muted)]", reviewedId === item.incident_id && "bg-[var(--positive-soft)] ring-2 ring-inset ring-[var(--positive)]")}><td className="px-5 py-4"><Link href={`/incidents/${item.incident_id}?return_to=${encodeURIComponent(returnTo)}`} onClick={() => sessionStorage.setItem("amex:incidents-scroll", String(window.scrollY))} className="block max-w-sm rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"><span className="mono text-[10px] font-bold text-[var(--ink-muted)]">{item.incident_id}</span><span className="mt-1 block text-sm font-bold leading-5">{item.title}</span>{reviewedId === item.incident_id ? <span className="mt-1 block text-[10px] font-extrabold uppercase tracking-wider text-[var(--positive)]">Review updated</span> : null}</Link></td><td className="px-4 py-4"><div className="flex flex-col items-start gap-2"><Badge tone={severityTone(item.severity)}>{item.severity}</Badge><span className="text-xs font-semibold text-[var(--ink-soft)]">{item.lifecycle.replaceAll("_", " ").toLowerCase()}</span></div></td><td className="px-4 py-4 text-xs leading-5"><strong>{item.affected_scope?.processing_region ?? "Global"}</strong><br /><span className="text-[var(--ink-muted)]">{item.affected_scope?.payment_method?.replaceAll("_", " ").toLowerCase() ?? "All methods"}</span></td><td className="mono px-4 py-4 text-xs">{item.dominant_error_signature ?? "Not established"}</td><td className="px-4 py-4">{item.evidence_completeness ? <Badge tone={item.evidence_completeness === "COMPLETE" ? "positive" : "warning"}>{item.evidence_completeness}</Badge> : <span className="text-xs text-[var(--ink-muted)]">Pending</span>}<p className="mt-2 text-[10px] text-[var(--ink-muted)]">Review {item.human_review_status.toLowerCase()}</p></td><td className="px-4 py-4 text-xs"><time dateTime={item.started_at} title={formatUtcDateTime(item.started_at)}>{formatLocalDateTime(item.started_at)} local</time></td></tr>; })}</tbody></table></div>{loaded && items.length === 0 ? <div className="p-10 text-center"><p className="font-bold">{sourceItems.length === 0 ? "No incidents yet." : "No incidents match these filters."}</p><p className="mt-2 text-sm text-[var(--ink-muted)]">{sourceItems.length === 0 ? "An investigation will appear after measured persistence rules open an incident." : null}</p>{sourceItems.length ? <button onClick={clearFilters} className="mt-2 text-sm font-semibold text-[var(--accent)] underline underline-offset-4">Clear filters</button> : null}</div> : null}</div><p aria-live="polite" className="mt-4 text-xs text-[var(--ink-muted)]">{loadError || (!loaded ? "Loading live incidents…" : `Showing ${items.length} of ${sourceItems.length} incidents · no next cursor`)}</p></div></AppShell>;
}
