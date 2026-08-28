"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { Accordion as RadixAccordion } from "radix-ui";
import { cn } from "@/lib/utils";

export const Accordion = RadixAccordion.Root;

export function AccordionItem({ className, ...props }: React.ComponentPropsWithoutRef<typeof RadixAccordion.Item>): React.JSX.Element {
  return <RadixAccordion.Item className={cn("border-b border-[var(--line)] last:border-b-0", className)} {...props} />;
}

export function AccordionTrigger({ children, className, ...props }: React.ComponentPropsWithoutRef<typeof RadixAccordion.Trigger>): React.JSX.Element {
  return (
    <RadixAccordion.Header>
      <RadixAccordion.Trigger className={cn("group flex w-full items-center justify-between gap-4 py-4 text-left text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]", className)} {...props}>
        {children}<ChevronDown aria-hidden="true" className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
      </RadixAccordion.Trigger>
    </RadixAccordion.Header>
  );
}

export function AccordionContent({ className, ...props }: React.ComponentPropsWithoutRef<typeof RadixAccordion.Content>): React.JSX.Element {
  return <RadixAccordion.Content className={cn("overflow-hidden pb-4 text-sm text-[var(--ink-soft)] data-[state=open]:animate-[accordion-down_180ms_ease-out]", className)} {...props} />;
}
