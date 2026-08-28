import * as React from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "positive" | "warning" | "danger" | "info";

const tones: Record<Tone, string> = {
  neutral: "bg-[var(--surface-muted)] text-[var(--ink-soft)] border-[var(--line)]",
  positive: "bg-[var(--positive-soft)] text-[var(--positive)] border-[color-mix(in_srgb,var(--positive)_25%,transparent)]",
  warning: "bg-[var(--warning-soft)] text-[var(--warning)] border-[color-mix(in_srgb,var(--warning)_28%,transparent)]",
  danger: "bg-[var(--danger-soft)] text-[var(--danger)] border-[color-mix(in_srgb,var(--danger)_25%,transparent)]",
  info: "bg-[var(--accent-soft)] text-[var(--accent)] border-[color-mix(in_srgb,var(--accent)_22%,transparent)]"
};

export function Badge({ tone = "neutral", className, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }): React.JSX.Element {
  return <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[0.68rem] font-bold uppercase tracking-[0.1em]", tones[tone], className)} {...props} />;
}
