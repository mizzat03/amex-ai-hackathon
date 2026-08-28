"use client";

import * as React from "react";
import { Tooltip as RadixTooltip } from "radix-ui";

export function Tooltip({ children, label }: { children: React.ReactNode; label: string }): React.JSX.Element {
  return (
    <RadixTooltip.Provider delayDuration={250}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content sideOffset={6} className="z-[70] rounded-lg bg-[var(--ink)] px-2.5 py-1.5 text-xs text-[var(--surface)] shadow-lg">
            {label}<RadixTooltip.Arrow className="fill-[var(--ink)]" />
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
}
