import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { IncidentWorkspace } from "@/components/investigator/incident-workspace";
import { FixtureInvestigatorRepository } from "@/data/repositories/fixture-repository";
import { fixtureRepository } from "@/data/repositories/fixture-repository";

it("shows the approved decisive facts above the evidence sections", () => {
  render(<IncidentWorkspace repository={fixtureRepository} />);
  expect(screen.getByText("UPSTREAM_TIMEOUT", { exact: true })).toBeVisible();
  expect(screen.getAllByText(/v2.4.1 deployment is temporally and dimensionally aligned/)).toHaveLength(2);
  expect(screen.getByRole("heading", { name: "What is known, derived, and missing" })).toBeVisible();
});

it("opens a non-modal resizable Copilot split pane without fixture controls", async () => {
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={fixtureRepository} />);
  await user.click(screen.getByRole("button", { name: "Open Copilot" }));
  expect(screen.getByRole("complementary", { name: "Evidence Copilot" })).toBeVisible();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Review a fixture state")).not.toBeInTheDocument();
  expect(screen.getByRole("separator", { name: "Resize Copilot pane" })).toBeVisible();
  expect(screen.getByRole("heading", { name: /Elevated technical errors/ })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Close Copilot" }));
  expect(screen.queryByRole("complementary", { name: "Evidence Copilot" })).not.toBeInTheDocument();
});

it("validates a rejecting human review note", async () => {
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={fixtureRepository} />);
  await user.selectOptions(screen.getByLabelText("Decision"), "REJECTED");
  await user.click(screen.getByRole("button", { name: "Save review" }));
  expect(screen.getByRole("alert")).toHaveTextContent("at least 12 characters");
});

it("returns to the preserved incident-list URL only after a successful review save", async () => {
  const user = userEvent.setup();
  const navigate = vi.fn();
  window.history.replaceState({}, "", "/incidents/INC-2026-0827-017?return_to=%2Fincidents%3Fseverity%3DSEV1%26sort%3Dstarted_at-desc");
  render(<IncidentWorkspace repository={fixtureRepository} navigate={navigate} />);

  await user.click(screen.getByRole("button", { name: "Save review" }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(
    "/incidents?severity=SEV1&sort=started_at-desc&reviewed=INC-2026-0827-017",
  ));
  expect(sessionStorage.getItem("amex:review-success")).toContain("Review saved as acknowledged");
});

it("rejects a return target outside the incident-list route", () => {
  window.history.replaceState(
    {},
    "",
    "/incidents/INC-2026-0827-017?return_to=%2Fincidents-export%3Fformat%3Draw",
  );

  render(<IncidentWorkspace repository={fixtureRepository} />);

  expect(screen.getByRole("link", { name: "All incidents" })).toHaveAttribute(
    "href",
    "/incidents",
  );
});

it("keeps review input and does not navigate when persistence fails", async () => {
  class FailingReviewRepository extends FixtureInvestigatorRepository {
    override async updateHumanReview(): Promise<never> {
      throw new Error("The review service is temporarily unavailable.");
    }
  }

  const user = userEvent.setup();
  const navigate = vi.fn();
  render(<IncidentWorkspace repository={new FailingReviewRepository()} navigate={navigate} />);
  await user.selectOptions(screen.getByLabelText("Decision"), "REJECTED");
  await user.type(screen.getByLabelText(/Review note/), "Evidence does not support this cause.");
  await user.click(screen.getByRole("button", { name: "Save review" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
  expect(screen.getByLabelText("Decision")).toHaveValue("REJECTED");
  expect(screen.getByLabelText(/Review note/)).toHaveValue("Evidence does not support this cause.");
  expect(navigate).not.toHaveBeenCalled();
});
