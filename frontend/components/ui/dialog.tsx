"use client";

import * as React from "react";
import { X } from "lucide-react";
import { Dialog as RadixDialog } from "radix-ui";
import { cn } from "@/lib/utils";

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;
export const DialogClose = RadixDialog.Close;

export function DialogContent({ children, className, title, description, ...props }: React.ComponentPropsWithoutRef<typeof RadixDialog.Content> & { title: string; description?: string }): React.JSX.Element {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-[2px]" />
      <RadixDialog.Content className={cn("fixed left-1/2 top-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-6 shadow-2xl outline-none", className)} {...props}>
        <RadixDialog.Title className="text-lg font-bold text-[var(--ink)]">{title}</RadixDialog.Title>
        {description ? <RadixDialog.Description className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">{description}</RadixDialog.Description> : null}
        <div className="mt-5">{children}</div>
        <RadixDialog.Close aria-label="Close dialog" className="absolute right-4 top-4 rounded-lg p-2 text-[var(--ink-muted)] outline-none hover:bg-[var(--surface-muted)] focus-visible:ring-2 focus-visible:ring-[var(--focus)]"><X aria-hidden="true" className="size-4" /></RadixDialog.Close>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}
