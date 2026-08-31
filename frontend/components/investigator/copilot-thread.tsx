"use client";

import * as React from "react";
import { AlertCircle, RotateCcw, Send, Sparkles } from "lucide-react";
import type { components } from "@/generated/api-types";
import { CopilotMessage } from "@/components/investigator/copilot-message";
import { Button } from "@/components/ui/button";
import type { InvestigatorRepository } from "@/data/repositories/investigator-repository";
import { progressLabel } from "@/lib/copilot-display";

type Api = components["schemas"];

function waitForNextPoll(delayMs: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve(); return; }
    const timer = window.setTimeout(finish, delayMs);
    function finish(): void {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    }
    signal.addEventListener("abort", finish, { once: true });
  });
}

export function CopilotThread({ incidentId, repository }: { incidentId: string; repository: InvestigatorRepository }): React.JSX.Element {
  const [messages, setMessages] = React.useState<Api["CopilotMessage"][]>([]);
  const [interaction, setInteraction] = React.useState<Api["CopilotInteractionView"] | null>(null);
  const [question, setQuestion] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const initialRequested = React.useRef(false);
  const composer = React.useRef<HTMLTextAreaElement>(null);
  const pollController = React.useRef<AbortController | null>(null);

  const loadThread = React.useCallback(async (): Promise<Api["CopilotMessage"][]> => {
    const response = await repository.getCopilotThread(incidentId);
    const items = [...response.messages.items];
    let cursor = response.messages.next_cursor ?? undefined;
    while (cursor) {
      const page = await repository.getCopilotMessages(incidentId, cursor);
      items.push(...page.items); cursor = page.next_cursor ?? undefined;
    }
    items.sort((left, right) => left.sequence - right.sequence);
    setMessages(items); setLoading(false); setNotice("");
    return items;
  }, [incidentId, repository]);

  const poll = React.useCallback(async (interactionId: string): Promise<void> => {
    pollController.current?.abort();
    const controller = new AbortController();
    pollController.current = controller;
    let attempt = 0;
    try {
      while (!controller.signal.aborted) {
        try {
          const next = await repository.getCopilotInteraction(incidentId, interactionId);
          if (controller.signal.aborted) return;
          setInteraction(next);
          if (["VALIDATED", "FALLBACK", "FAILED"].includes(next.status)) {
            try {
              await loadThread();
              return;
            } catch {
              if (controller.signal.aborted) return;
              setNotice("Analysis completed, but the transcript could not be refreshed. Retrying…");
            }
          }
        } catch {
          if (controller.signal.aborted) return;
          setNotice("The status connection was interrupted. Retrying automatically…");
        }
        attempt += 1;
        if (attempt === 30) {
          setNotice("Analysis is taking longer than usual. This page will keep checking for the validated result.");
        }
        await waitForNextPoll(Math.min(500 + Math.floor(attempt / 10) * 250, 2_000), controller.signal);
      }
    } finally {
      if (pollController.current === controller) pollController.current = null;
    }
  }, [incidentId, loadThread, repository]);

  const requestInitial = React.useCallback(async (): Promise<void> => {
    try {
      const next = await repository.requestInitialCopilotReport(incidentId);
      setInteraction(next);
      if (next.status === "QUEUED" || next.status === "IN_PROGRESS") void poll(next.interaction_id);
      else await loadThread();
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : "The initial report request could not be confirmed.");
    }
  }, [incidentId, loadThread, poll, repository]);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadThread()
        .then((items) => {
          if (!items.some((item) => item.role === "ASSISTANT") && !initialRequested.current) {
            initialRequested.current = true;
            void requestInitial();
          }
        })
        .catch((cause: unknown) => {
          setLoading(false);
          setNotice(cause instanceof Error ? cause.message : "The Copilot thread could not be loaded.");
        });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadThread, requestInitial]);
  React.useEffect(() => () => pollController.current?.abort(), []);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault(); const trimmed = question.trim();
    if (trimmed.length < 8) { setNotice("Enter at least 8 characters."); return; }
    try {
      const accepted = await repository.submitCopilotMessage(incidentId, { question: trimmed, client_request_id: crypto.randomUUID(), referenced_message_ids: [] });
      setQuestion(""); setNotice("Question accepted."); await loadThread();
      setInteraction({ interaction_id: accepted.interaction_id, incident_id: incidentId, thread_id: accepted.thread_id, status: "QUEUED", progress_stage: "QUEUED", progress_updated_at: accepted.accepted_at, validated_message_id: null, deterministic_fallback: null, retry: { eligible: false, unavailable_reason: "Interaction is queued", retry_after: null } });
      void poll(accepted.interaction_id);
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : "The question could not be submitted."); }
  }

  async function retry(message: Api["CopilotMessage"]): Promise<void> {
    if (!message.interaction_id) return;
    try { const next = await repository.retryCopilotInteraction(incidentId, message.interaction_id); setInteraction(next); void poll(next.interaction_id); }
    catch (cause) { setNotice(cause instanceof Error ? cause.message : "Retry was not accepted."); }
  }

  function suggest(value: string): void { setQuestion(value); window.setTimeout(() => composer.current?.focus(), 0); }
  const processing = interaction?.status === "QUEUED" || interaction?.status === "IN_PROGRESS";
  return <section aria-label="Evidence Copilot" className="copilot-workspace"><header className="border-b border-[var(--line)] px-5 py-5 sm:px-7"><div className="flex items-start gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]"><Sparkles aria-hidden="true" className="size-4" /></span><div><h2 className="text-xl font-extrabold">Evidence Copilot</h2><p className="mt-1 text-xs leading-5 text-[var(--ink-muted)]">One incident-scoped thread. Answers are validated against their pinned evidence version and cannot perform remediation.</p></div></div></header><div className="copilot-transcript" aria-live="polite">{loading ? <p className="rounded-xl border border-[var(--line)] p-4 text-sm">Restoring the investigation thread…</p> : null}{!loading && !messages.length && !processing ? <div className="rounded-xl border border-[var(--line)] p-5"><p className="font-bold">Preparing the initial evidence briefing</p><p className="mt-2 text-sm text-[var(--ink-muted)]">The service will persist the result here when validation completes.</p></div> : null}{messages.map((message) => <CopilotMessage key={message.message_id} message={message} onSuggestion={suggest} onFeedback={(messageId, request) => repository.submitCopilotFeedback(incidentId, messageId, request).then(() => undefined)} onRetry={retry} />)}{processing ? <div className="copilot-message" aria-live="polite"><p className="flex items-center gap-2 text-sm font-bold"><span className="status-pulse size-2 rounded-full bg-[var(--accent)]" />{progressLabel(interaction.progress_stage)}</p><ol className="mt-3 grid gap-2 text-xs text-[var(--ink-muted)] sm:grid-cols-3"><li>1. Evidence pinned</li><li>2. Analysis controlled</li><li>3. Response validated</li></ol></div> : null}{interaction?.status === "FAILED" ? <div role="alert" className="copilot-message border-[color-mix(in_srgb,var(--danger)_30%,var(--line))]"><p className="flex items-center gap-2 font-bold text-[var(--danger)]"><AlertCircle aria-hidden="true" className="size-4" />Copilot could not complete</p><p className="mt-2 text-sm">No unvalidated provider content was displayed.</p>{interaction.retry.eligible ? <Button className="mt-3" size="sm" variant="secondary" onClick={() => void repository.retryCopilotInteraction(incidentId, interaction.interaction_id).then((next) => { setInteraction(next); void poll(next.interaction_id); })}><RotateCcw aria-hidden="true" className="size-3" />Retry analysis</Button> : null}</div> : null}</div><form className="copilot-composer" onSubmit={submit}><label htmlFor="copilot-question" className="text-xs font-bold">Ask about this incident evidence</label><div className="mt-2 flex items-end gap-2"><textarea ref={composer} id="copilot-question" value={question} onChange={(event) => setQuestion(event.target.value)} minLength={8} required rows={2} placeholder="What evidence weakens the leading hypothesis?" className="min-h-12 min-w-0 flex-1 resize-y rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]" /><Button type="submit" size="icon" aria-label="Submit question"><Send aria-hidden="true" className="size-4" /></Button></div><p role={notice ? "status" : undefined} className="mt-2 min-h-4 text-xs text-[var(--ink-muted)]">{notice}</p></form></section>;
}
