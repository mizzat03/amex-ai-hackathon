"use client";

import * as React from "react";
import { X } from "lucide-react";
import { Dialog as RadixDialog } from "radix-ui";
import { cn } from "@/lib/utils";

export const Sheet = RadixDialog.Root;
export const SheetTrigger = RadixDialog.Trigger;

export function SheetContent({ children, className, title, description, ...props }: React.ComponentPropsWithoutRef<typeof RadixDialog.Content> & { title: string; description: string }): React.JSX.Element {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-50 bg-slate-950/35" />
      <RadixDialog.Content className={cn("fixed inset-y-0 right-0 z-50 w-[min(94vw,31rem)] overflow-y-auto border-l border-[var(--line)] bg-[var(--surface)] p-6 shadow-2xl outline-none", className)} {...props}>
        <RadixDialog.Title className="text-lg font-bold">{title}</RadixDialog.Title>
        <RadixDialog.Description className="mt-1 text-sm text-[var(--ink-soft)]">{description}</RadixDialog.Description>
        <div className="mt-6">{children}</div>
        <RadixDialog.Close aria-label="Close Copilot" className="absolute right-4 top-4 rounded-lg p-2 text-[var(--ink-muted)] outline-none hover:bg-[var(--surface-muted)] focus-visible:ring-2 focus-visible:ring-[var(--focus)]"><X aria-hidden="true" className="size-4" /></RadixDialog.Close>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}
