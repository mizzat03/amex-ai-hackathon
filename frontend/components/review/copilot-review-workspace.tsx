"use client";

import * as React from "react";
import { IncidentWorkspace } from "@/components/investigator/incident-workspace";
import {
  copilotTranscriptFixtures,
  copilotThreadFixture,
  type Api,
} from "@/data/fixtures/scenarios";
import { FixtureInvestigatorRepository } from "@/data/repositories/fixture-repository";

export type CopilotReviewState = "initial" | "follow-up" | "transition" | "fallback" | "restored";

class CopilotReviewRepository extends FixtureInvestigatorRepository {
  constructor(private readonly state: CopilotReviewState) { super(); }

  override async getCopilotThread(): Promise<Api["CopilotThreadResponse"]> {
    const messages = {
      initial: copilotTranscriptFixtures.initial,
      "follow-up": copilotTranscriptFixtures.followUp,
      transition: copilotTranscriptFixtures.transition,
      fallback: copilotTranscriptFixtures.fallback,
      restored: copilotTranscriptFixtures.restored,
    }[this.state];
    const reviewMessages = messages as readonly unknown[];
    return {
      thread: structuredClone(copilotThreadFixture.thread),
      messages: {
        items: reviewMessages.map((message) => structuredClone(message) as Api["CopilotMessage"]),
        next_cursor: null,
      },
    };
  }
}

export function CopilotReviewWorkspace({ state }: { state: CopilotReviewState }): React.JSX.Element {
  const repository = React.useMemo(() => new CopilotReviewRepository(state), [state]);
  return <IncidentWorkspace repository={repository} navigate={() => undefined} />;
}
