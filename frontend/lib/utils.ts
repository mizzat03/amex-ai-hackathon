import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatPercent(value: number | null, precision = 2): string {
  return value === null ? "Unavailable" : `${(value * 100).toFixed(precision)}%`;
}

export function formatMetric(value: number | null, unit: string): string {
  if (value === null) return "Unavailable";
  if (unit === "RATE") return formatPercent(value);
  if (unit === "MILLISECONDS") return `${Math.round(value)} ms`;
  if (unit === "ATTEMPTS_PER_SECOND") return `${Math.round(value).toLocaleString()} /s`;
  return Math.round(value).toLocaleString();
}

export function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function formatLocalDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium"
  }).format(new Date(value));
}

export function formatUtcDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "long",
    timeZone: "UTC"
  }).format(new Date(value));
}
