"use client";

import * as React from "react";
import Link from "next/link";
import { Activity, FileClock, LayoutDashboard, Moon, ShieldCheck, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type ShellMode = "overview" | "investigation";

function ThemeToggle(): React.JSX.Element {
  const [dark, setDark] = React.useState(false);

  function toggleTheme(): void {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
  }

  return (
    <Tooltip label={dark ? "Use light theme" : "Use dark theme"}>
      <Button aria-label={dark ? "Use light theme" : "Use dark theme"} variant="ghost" size="icon" onClick={toggleTheme}>
        {dark ? <Sun aria-hidden="true" className="size-4" /> : <Moon aria-hidden="true" className="size-4" />}
      </Button>
    </Tooltip>
  );
}

const navItems = [
  { label: "Overview", icon: LayoutDashboard, href: "/" },
  { label: "Incidents", icon: FileClock, href: "/incidents" }
] as const;

type AppShellProps = {
  children: React.ReactNode;
  mode?: ShellMode;
  active?: "Overview" | "Incidents";
};

export function AppShell({ children, mode = "overview", active = "Overview" }: AppShellProps): React.JSX.Element {
  if (mode === "overview") {
    return (
      <div className="min-h-screen bg-[var(--canvas)]">
        <header className="sticky top-0 z-40 border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--canvas)_92%,transparent)] backdrop-blur-xl">
          <div className="mx-auto flex h-16 max-w-[1500px] items-center gap-6 px-5 sm:px-7 lg:px-9">
            <Link href="/" className="flex items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]">
              <span className="grid size-9 place-items-center rounded-xl bg-[var(--ink)] text-[var(--surface)]"><Activity aria-hidden="true" className="size-4" /></span>
              <span><span className="block text-sm font-extrabold tracking-tight">Incident Investigator</span><span className="block text-[10px] font-bold uppercase tracking-[.16em] text-[var(--ink-muted)]">Analyst ledger</span></span>
            </Link>
            <nav aria-label="Primary" className="ml-1 flex h-full items-center gap-1 sm:ml-6">
              {navItems.map((item) => <Link key={item.label} href={item.href} aria-current={active === item.label ? "page" : undefined} className={cn("flex h-full items-center border-b-2 px-3 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus)] sm:px-4", active === item.label ? "border-[var(--accent)] text-[var(--ink)]" : "border-transparent text-[var(--ink-muted)] hover:text-[var(--ink)]")}>{item.label}</Link>)}
            </nav>
            <div className="ml-auto"><ThemeToggle /></div>
          </div>
        </header>
        <main>{children}</main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--canvas)] lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="hidden min-h-screen border-r border-[var(--line)] bg-[var(--surface)] px-4 py-6 lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col">
        <Link href="/" className="flex items-center gap-3 rounded-xl px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]">
          <span className="grid size-10 place-items-center rounded-xl bg-[var(--ink)] text-[var(--surface)]"><Activity aria-hidden="true" className="size-5" /></span>
          <span className="text-sm font-extrabold tracking-tight">Incident<br />Investigator</span>
        </Link>
        <nav aria-label="Primary" className="mt-10 space-y-1">
          {navItems.map((item) => { const Icon = item.icon; return <Link key={item.label} href={item.href} aria-current={active === item.label ? "page" : undefined} className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--focus)]", active === item.label ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-[var(--ink-muted)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)]")}><Icon aria-hidden="true" className="size-4" />{item.label}</Link>; })}
        </nav>
        <div className="mt-auto rounded-2xl border border-[var(--line)] bg-[var(--surface-muted)] p-4">
          <div className="flex items-center gap-2 text-xs font-bold"><ShieldCheck aria-hidden="true" className="size-4 text-[var(--positive)]" />Evidence boundary</div>
          <p className="mt-2 text-xs leading-5 text-[var(--ink-muted)]">Deterministic findings remain available if Copilot validation fails.</p>
        </div>
        <div className="mt-3 flex items-center justify-between px-1"><span className="text-[10px] font-bold uppercase tracking-[.14em] text-[var(--ink-muted)]">Investigation workspace</span><ThemeToggle /></div>
      </aside>
      <div>
        <header className="sticky top-0 z-40 flex h-14 items-center border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--canvas)_90%,transparent)] px-5 backdrop-blur-xl lg:hidden"><Activity aria-hidden="true" className="mr-2 size-4" /><span className="text-sm font-bold">Incident Investigator</span><nav aria-label="Mobile primary" className="ml-4 flex gap-3 text-xs font-semibold"><Link href="/">Overview</Link><Link href="/incidents">Incidents</Link></nav><div className="ml-auto"><ThemeToggle /></div></header>
        <div>{children}</div>
      </div>
    </div>
  );
}
