"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import type { components } from "@/generated/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopilotCitation } from "@/components/investigator/copilot-citation";
import { confidenceLabel, isCopilotAnswer, isEvidenceNotice, isFallback, isLifecycleNotice, isUserQuestion } from "@/lib/copilot-display";
import { formatTime, formatUtcDateTime } from "@/lib/utils";

type Api = components["schemas"];
type Rating = Api["CopilotFeedbackRequest"]["rating"];

function PointList({ title, points = [], citations = [] }: { title: string; points?: Api["CopilotEvidencePoint"][] | undefined; citations?: Api["CopilotAnswerContent"]["citations"] | undefined }): React.JSX.Element | null {
  if (!points.length) return null;
  return <section><h4 className="text-xs font-extrabold uppercase tracking-[.1em] text-[var(--ink-muted)]">{title}</h4><ul className="mt-2 space-y-2">{points.map((point, index) => <li key={`${title}-${index}`} className="text-sm leading-6">{point.text}{(point.citation_numbers ?? []).map((number) => { const citation = citations.find((item) => item.citation_number === number); return citation ? <CopilotCitation key={number} citation={citation} /> : null; })}</li>)}</ul></section>;
}

function Feedback({ message, onFeedback }: { message: Api["CopilotMessage"]; onFeedback: (messageId: string, request: Api["CopilotFeedbackRequest"]) => Promise<void> }): React.JSX.Element {
  const [rating, setRating] = React.useState<Rating | null>(null);
  const [problemTypes, setProblemTypes] = React.useState<NonNullable<Api["CopilotFeedbackRequest"]["problem_types"]>>([]);
  const [note, setNote] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const tags = [
    ["INCORRECT_CLAIM", "Incorrect claim"], ["WEAK_EVIDENCE", "Weak evidence"],
    ["MISSED_ALTERNATIVE", "Missed alternative"], ["POOR_RECOMMENDATION", "Poor recommendation"],
    ["UNCLEAR_EXPLANATION", "Unclear explanation"], ["UNSAFE_SUGGESTION", "Unsafe suggestion"],
  ] as const;

  async function save(next: Rating): Promise<void> {
    await onFeedback(message.message_id, { rating: next, problem_types: problemTypes, note: note.trim() || null });
    setRating(next); setNotice("Feedback saved.");
  }

  return <details className="mt-5 rounded-xl bg-[var(--surface-muted)] p-3"><summary className="cursor-pointer text-xs font-bold">Rate this answer</summary><div className="mt-3"><div className="flex flex-wrap gap-2"><Button size="sm" variant={rating === "HELPFUL" ? "primary" : "secondary"} aria-pressed={rating === "HELPFUL"} onClick={() => void save("HELPFUL")}><ThumbsUp aria-hidden="true" className="size-3" />Helpful</Button><Button size="sm" variant={rating === "PARTIALLY_HELPFUL" ? "primary" : "secondary"} aria-pressed={rating === "PARTIALLY_HELPFUL"} onClick={() => void save("PARTIALLY_HELPFUL")}>Partly helpful</Button><Button size="sm" variant={rating === "NOT_HELPFUL" ? "primary" : "secondary"} aria-pressed={rating === "NOT_HELPFUL"} onClick={() => void save("NOT_HELPFUL")}><ThumbsDown aria-hidden="true" className="size-3" />Not helpful</Button></div><fieldset className="mt-4"><legend className="text-xs font-bold">Optional problem tags</legend><div className="mt-2 flex flex-wrap gap-2">{tags.map(([value, label]) => <label key={value} className="rounded-lg border border-[var(--line)] px-2 py-1 text-xs"><input type="checkbox" className="mr-1.5" checked={problemTypes.includes(value)} onChange={(event) => setProblemTypes((items) => event.target.checked ? [...items, value] : items.filter((item) => item !== value))} />{label}</label>)}</div></fieldset><label className="mt-4 block text-xs font-bold" htmlFor={`feedback-note-${message.message_id}`}>Optional note</label><textarea id={`feedback-note-${message.message_id}`} value={note} onChange={(event) => setNote(event.target.value)} className="mt-2 min-h-20 w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]" /><p role="status" className="mt-2 text-xs text-[var(--positive)]">{notice}</p></div></details>;
}

export function CopilotMessage({ message, onSuggestion, onFeedback, onRetry }: { message: Api["CopilotMessage"]; onSuggestion: (question: string) => void; onFeedback: (messageId: string, request: Api["CopilotFeedbackRequest"]) => Promise<void>; onRetry: (message: Api["CopilotMessage"]) => Promise<void> }): React.JSX.Element {
  const content = message.content;
  const timestamp = <time dateTime={message.created_at} title={formatUtcDateTime(message.created_at)} className="text-[11px] text-[var(--ink-muted)]">{formatTime(message.created_at)} local</time>;
  if (isUserQuestion(content)) return <article aria-label="Your question" className="copilot-message copilot-message-user"><div className="flex items-center justify-between gap-3"><p className="text-xs font-bold">You</p>{timestamp}</div><p className="mt-2 text-sm leading-6">{content.question}</p></article>;
  if (isEvidenceNotice(content) || isLifecycleNotice(content)) return <article role="status" className="copilot-message copilot-message-system"><div className="flex items-center justify-between gap-3"><Badge tone="info">{isEvidenceNotice(content) ? "Evidence updated" : content.lifecycle.replaceAll("_", " ").toLowerCase()}</Badge>{timestamp}</div><p className="mt-2 text-sm leading-6">{content.summary}</p></article>;
  if (isFallback(content)) return <article className="copilot-message copilot-message-fallback"><div className="flex items-center justify-between gap-3"><Badge tone="warning"><AlertTriangle aria-hidden="true" className="size-3" />Deterministic fallback</Badge>{timestamp}</div><p className="mt-3 text-sm leading-6">{content.summary}</p>{content.retry_eligible ? <Button className="mt-3" size="sm" variant="secondary" onClick={() => void onRetry(message)}><RotateCcw aria-hidden="true" className="size-3" />Retry analysis</Button> : null}</article>;
  if (!isCopilotAnswer(content)) return <article className="copilot-message"><p className="text-sm">This message type is unavailable.</p></article>;
  const checks = content.recommended_checks ?? [];
  const citations = content.citations ?? [];
  const suggestions = content.suggested_questions ?? [];
  return <article aria-label={content.answer_kind === "initial_report" ? "Initial Copilot briefing" : "Copilot follow-up answer"} className="copilot-message copilot-message-assistant"><header className="flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap items-center gap-2"><Badge tone="positive"><CheckCircle2 aria-hidden="true" className="size-3" />Validated</Badge><Badge tone="info">{confidenceLabel(content.confidence)}</Badge>{message.evidence_package_version ? <span className="text-xs text-[var(--ink-muted)]">Evidence version {message.evidence_package_version}</span> : null}</div>{timestamp}</header><h3 className="mt-4 text-xl font-extrabold tracking-tight">{content.headline}</h3><p className="mt-3 text-sm font-semibold leading-6">{content.direct_answer}</p><div className="mt-5 grid gap-5"><PointList title="Supporting evidence" points={content.supporting_points} citations={citations} /><PointList title="Contradictory evidence" points={content.contradictory_points} citations={citations} /><PointList title="What remains unknown" points={content.unknown_points} citations={citations} />{checks.length ? <section><h4 className="text-xs font-extrabold uppercase tracking-[.1em] text-[var(--ink-muted)]">Recommended checks</h4><ol className="mt-2 space-y-3">{checks.map((check, index) => <li key={`${check.title}-${index}`} className="rounded-xl border border-[var(--line)] p-3"><p className="text-sm font-bold">{check.title}</p><p className="mt-1 text-sm leading-6">{check.rationale}</p><p className="mt-1 text-xs text-[var(--ink-muted)]">Expected signal: {check.expected_signal} · {check.risk.toLowerCase()} risk · human approval required</p>{(check.citation_numbers ?? []).map((number) => { const citation = citations.find((item) => item.citation_number === number); return citation ? <CopilotCitation key={number} citation={citation} /> : null; })}</li>)}</ol></section> : null}</div>{suggestions.length ? <div className="mt-5"><p className="text-xs font-bold">Continue investigating</p><div className="mt-2 flex flex-wrap gap-2">{suggestions.map((question) => <Button key={question} size="sm" variant="secondary" onClick={() => onSuggestion(question)}>{question}</Button>)}</div></div> : null}<Feedback message={message} onFeedback={onFeedback} /></article>;
}
