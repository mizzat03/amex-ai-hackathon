import { render, screen } from "@testing-library/react";
import { StateGallery } from "@/components/review/state-gallery";
import { requiredStateFixtures } from "@/data/fixtures/scenarios";
import { fixtureRepository } from "@/data/repositories/fixture-repository";

it("renders every mandated fixture-state family", () => {
  render(<StateGallery />);
  for (const state of [
    ...requiredStateFixtures.telemetry,
    ...requiredStateFixtures.lifecycle,
    ...requiredStateFixtures.completeness,
    ...requiredStateFixtures.copilot,
    ...requiredStateFixtures.review,
    ...requiredStateFixtures.feedback
  ]) {
    expect(screen.getByText(state.replaceAll("_", " "), { exact: true })).toBeVisible();
  }
  expect(screen.getByText("Insufficient evidence", { exact: true })).toBeVisible();
});

it("keeps repository responses isolated from fixture mutations", async () => {
  const first = await fixtureRepository.getOverview();
  first.active_incidents.length = 0;
  const second = await fixtureRepository.getOverview();
  expect(second.active_incidents).toHaveLength(1);
});
