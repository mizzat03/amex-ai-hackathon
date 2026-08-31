import { CopilotReviewWorkspace, type CopilotReviewState } from "@/components/review/copilot-review-workspace";
import { StateGallery } from "@/components/review/state-gallery";

const reviewStates = new Set<CopilotReviewState>(["initial", "follow-up", "transition", "fallback", "restored"]);

export default async function Page({ searchParams }: { searchParams: Promise<{ copilot?: string }> }): Promise<React.JSX.Element> {
  const state = (await searchParams).copilot as CopilotReviewState | undefined;
  return state && reviewStates.has(state) ? <CopilotReviewWorkspace state={state} /> : <StateGallery />;
}
