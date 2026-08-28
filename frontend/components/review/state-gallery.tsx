import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { requiredStateFixtures } from "@/data/fixtures/scenarios";

const groups = [
  ["Telemetry", requiredStateFixtures.telemetry],
  ["Lifecycle", requiredStateFixtures.lifecycle],
  ["Evidence completeness", requiredStateFixtures.completeness],
  ["Copilot interaction", requiredStateFixtures.copilot],
  ["Connection", requiredStateFixtures.reconnect.map((state) => state.status)],
  ["Human review", requiredStateFixtures.review],
  ["Feedback", requiredStateFixtures.feedback]
] as const;

export function StateGallery(): React.JSX.Element {
  return <main className="mx-auto max-w-6xl p-8"><p className="eyebrow">Design review support</p><h1 className="mt-2 text-4xl font-black tracking-tight">Required fixture states</h1><p className="mt-3 text-sm text-[var(--ink-soft)]">Every mandated state has an explicit render target. Copilot states are also interactive in each incident workspace.</p><div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{groups.map(([title, states]) => <Card key={title}><CardHeader><h2 className="font-bold">{title}</h2><Badge tone="neutral">{states.length}</Badge></CardHeader><CardContent className="flex flex-wrap gap-2">{states.map((state) => <Badge key={state} tone={String(state).includes("FAIL") || state === "INVALID" || state === "UNKNOWN" || state === "disconnected" ? "danger" : String(state).includes("RECOVERY") || state === "PARTIAL" || state === "STALE" || state === "reconnecting" ? "warning" : "info"}>{String(state).replaceAll("_", " ")}</Badge>)}</CardContent></Card>)}</div><Card className="mt-4"><CardHeader><h2 className="font-bold">RCA empty-result state</h2><Badge tone="warning">Insufficient evidence</Badge></CardHeader><CardContent><p className="text-sm text-[var(--ink-soft)]">No operational event is both temporally close and scope-consistent. The UI shows this limitation instead of selecting a weak cause.</p></CardContent></Card></main>;
}
