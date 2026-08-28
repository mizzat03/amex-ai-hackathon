"use client";

import * as React from "react";
import { Tabs as RadixTabs } from "radix-ui";
import { cn } from "@/lib/utils";

export const Tabs = RadixTabs.Root;

export function TabsList({ className, ...props }: React.ComponentPropsWithoutRef<typeof RadixTabs.List>): React.JSX.Element {
  return <RadixTabs.List className={cn("inline-flex rounded-xl border border-[var(--line)] bg-[var(--surface-muted)] p-1", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: React.ComponentPropsWithoutRef<typeof RadixTabs.Trigger>): React.JSX.Element {
  return <RadixTabs.Trigger className={cn("rounded-lg px-3 py-1.5 text-xs font-semibold text-[var(--ink-muted)] outline-none data-[state=active]:bg-[var(--surface)] data-[state=active]:text-[var(--ink)] data-[state=active]:shadow-sm focus-visible:ring-2 focus-visible:ring-[var(--focus)]", className)} {...props} />;
}

export function TabsContent({ className, ...props }: React.ComponentPropsWithoutRef<typeof RadixTabs.Content>): React.JSX.Element {
  return <RadixTabs.Content className={cn("outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]", className)} {...props} />;
}
