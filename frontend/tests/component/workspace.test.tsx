import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { CopilotThread } from "@/components/investigator/copilot-thread";
import { IncidentWorkspace } from "@/components/investigator/incident-workspace";
import { copilotFallbackFixture, copilotMessageFixture, copilotThreadFixture, workspaceFixture } from "@/data/fixtures/scenarios";
import { FixtureInvestigatorRepository } from "@/data/repositories/fixture-repository";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("presents technical incident labels and the leading RCA in a human-friendly hierarchy", async () => {
  const technicalSummary = "The observed PAYMENT_GATEWAY v2.4.1 deployment may have introduced the TOKEN_VALIDATION_FAILED regression.";
  class TechnicalLabelsRepository extends FixtureInvestigatorRepository {
    override async getIncident() {
      const workspace = structuredClone(workspaceFixture);
      workspace.affected_scope = {
        ...workspace.affected_scope!,
        label: "MOBILE_WALLET + v2.4.1",
        scope: { ...workspace.affected_scope!.scope, payment_method: "MOBILE_WALLET", service_version: "v2.4.1" },
      };
      workspace.error_signature = {
        ...workspace.error_signature!,
        normalized_error_code: "TOKEN_VALIDATION_FAILED",
        label: "Dominant error signature (symptom): TOKEN_VALIDATION_FAILED",
      };
      workspace.rca_summary.leading_hypothesis = {
        ...workspace.rca_summary.leading_hypothesis!,
        candidate_type: "DEPLOYMENT",
        summary: technicalSummary,
      };
      return workspace;
    }
  }

  const user = userEvent.setup();
  render(<IncidentWorkspace repository={new TechnicalLabelsRepository()} />);

  expect(await screen.findAllByText("Mobile wallet · v2.4.1", { exact: true })).toHaveLength(2);
  expect(screen.getAllByText("Token validation failed", { exact: true })).toHaveLength(2);
  expect(screen.getByRole("heading", { name: "Deployment is the leading explanation" })).toBeVisible();
  expect(screen.getByText(technicalSummary)).not.toBeVisible();

  await user.click(screen.getByText("Show technical hypothesis"));
  expect(screen.getByText(technicalSummary)).toBeVisible();
});

it("keeps checking until a slow Copilot interaction reaches a terminal state", async () => {
  class SlowCopilotRepository extends FixtureInvestigatorRepository {
    pollCount = 0;
    private complete = false;

    override async getCopilotThread() {
      const response = await super.getCopilotThread(workspaceFixture.incident_id);
      return {
        ...response,
        messages: {
          items: this.complete ? [structuredClone(copilotMessageFixture)] : [],
          next_cursor: null,
        },
      };
    }

    override async requestInitialCopilotReport() {
      const interaction = await super.requestInitialCopilotReport(workspaceFixture.incident_id);
      return {
        ...interaction,
        status: "QUEUED" as const,
        progress_stage: "QUEUED" as const,
        validated_message_id: null,
      };
    }

    override async getCopilotInteraction(_incidentId: string, interactionId: string) {
      const interaction = await super.getCopilotInteraction(workspaceFixture.incident_id, interactionId);
      this.pollCount += 1;
      if (this.pollCount <= 30) {
        return {
          ...interaction,
          status: "IN_PROGRESS" as const,
          progress_stage: "ANALYSING_EVIDENCE" as const,
          validated_message_id: null,
        };
      }
      this.complete = true;
      return interaction;
    }
  }

  vi.useFakeTimers();
  const repository = new SlowCopilotRepository();
  render(<CopilotThread incidentId={workspaceFixture.incident_id} repository={repository} />);

  await act(async () => {
    await vi.runAllTimersAsync();
  });

  expect(repository.pollCount).toBe(31);
  expect(screen.getByRole("article", { name: "Initial Copilot briefing" })).toBeVisible();
  expect(screen.queryByText("Analysing evidence")).not.toBeInTheDocument();
});

it("uses the approved accessible tab order and Open Copilot focus behavior", async () => {
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={new FixtureInvestigatorRepository()} />);
  const tablist = screen.getByRole("tablist", { name: "Incident workspace" });
  expect(within(tablist).getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Summary", "Timeline", "Evidence", "Copilot", "Review"]);
  await user.click(screen.getByRole("button", { name: "Open Copilot" }));
  expect(screen.getByRole("tab", { name: "Copilot" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tab", { name: "Copilot" })).toHaveFocus();
  expect(screen.getByRole("region", { name: "Evidence Copilot" })).toBeVisible();
  expect(screen.queryByRole("separator", { name: /Resize Copilot/ })).not.toBeInTheDocument();
  expect(screen.queryByText("Reset width")).not.toBeInTheDocument();
  expect(screen.queryByText(/new conversation/i)).not.toBeInTheDocument();
});

it("renders a concise validated briefing and hides technical IDs until citation expansion", async () => {
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={new FixtureInvestigatorRepository()} />);
  await user.click(screen.getByRole("button", { name: "Open Copilot" }));
  expect(await screen.findByRole("article", { name: "Initial Copilot briefing" })).toBeVisible();
  expect(screen.getByText(copilotMessageFixture.content.headline)).toBeVisible();
  expect(screen.getByText("High confidence")).toBeVisible();
  expect(screen.getAllByText("EV-SCOPE-001").every((item) => !item.offsetParent)).toBe(true);
  const citationToggle = screen.getAllByLabelText("Open citation 1")[0]!;
  const citationDetails = citationToggle.closest("details")!;
  await user.click(citationToggle);
  expect(within(citationDetails).getByText("Deterministic scope comparison")).toBeVisible();
  expect(screen.getAllByText("EV-SCOPE-001").every((item) => !item.offsetParent)).toBe(true);
  await user.click(within(citationDetails).getByText("Technical details"));
  expect(within(citationDetails).getByText("EV-SCOPE-001")).toBeVisible();
});

it("puts a suggested question into the sticky composer", async () => {
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={new FixtureInvestigatorRepository()} />);
  await user.click(screen.getByRole("button", { name: "Open Copilot" }));
  await user.click(await screen.findByRole("button", { name: "What evidence weakens this hypothesis?" }));
  expect(screen.getByLabelText("Ask about this incident evidence")).toHaveValue("What evidence weakens this hypothesis?");
  expect(screen.getByLabelText("Ask about this incident evidence")).toHaveFocus();
});

it("supports every approved feedback rating, optional tags, and an optional note", async () => {
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={new FixtureInvestigatorRepository()} />);
  await user.click(screen.getByRole("button", { name: "Open Copilot" }));
  await user.click(await screen.findByText("Rate this answer"));
  expect(screen.getByRole("button", { name: "Helpful" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Partly helpful" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Not helpful" })).toBeVisible();
  await user.click(screen.getByLabelText("Weak evidence"));
  await user.type(screen.getByLabelText("Optional note"), "Needs another comparison.");
  await user.click(screen.getByRole("button", { name: "Partly helpful" }));
  expect(await screen.findByText("Feedback saved.")).toBeVisible();
});

it("persists a labelled fallback in the transcript and keeps the composer usable", async () => {
  class FallbackRepository extends FixtureInvestigatorRepository {
    override async getCopilotThread() {
      return { ...structuredClone(copilotThreadFixture), messages: { items: [structuredClone(copilotFallbackFixture)], next_cursor: null } };
    }
  }
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={new FallbackRepository()} />);
  await user.click(screen.getByRole("button", { name: "Open Copilot" }));
  expect(await screen.findByText("Deterministic fallback")).toBeVisible();
  expect(screen.queryByText("provider_http_failure")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Ask about this incident evidence")).toBeEnabled();
});

it("validates a rejecting human review note", async () => {
  const user = userEvent.setup();
  render(<IncidentWorkspace repository={new FixtureInvestigatorRepository()} />);
  await user.click(screen.getByRole("tab", { name: "Review" }));
  await user.selectOptions(screen.getByLabelText("Decision"), "REJECTED");
  await user.click(screen.getByRole("button", { name: "Save review" }));
  expect(screen.getByRole("alert")).toHaveTextContent("at least 12 characters");
});

it("returns to the preserved incident-list URL only after a successful review save", async () => {
  const user = userEvent.setup(); const navigate = vi.fn();
  window.history.replaceState({}, "", "/incidents/INC-2026-0827-017?return_to=%2Fincidents%3Fseverity%3DSEV1%26sort%3Dstarted_at-desc");
  render(<IncidentWorkspace repository={new FixtureInvestigatorRepository()} navigate={navigate} />);
  await user.click(screen.getByRole("tab", { name: "Review" }));
  await user.click(screen.getByRole("button", { name: "Save review" }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/incidents?severity=SEV1&sort=started_at-desc&reviewed=INC-2026-0827-017"));
});

it("rejects a return target outside the incident-list route", () => {
  window.history.replaceState({}, "", "/incidents/INC-2026-0827-017?return_to=%2Fincidents-export%3Fformat%3Draw");
  render(<IncidentWorkspace repository={new FixtureInvestigatorRepository()} />);
  expect(screen.getByRole("link", { name: "All incidents" })).toHaveAttribute("href", "/incidents");
});

it("keeps review input and does not navigate when persistence fails", async () => {
  class FailingReviewRepository extends FixtureInvestigatorRepository { override async updateHumanReview(): Promise<never> { throw new Error("The review service is temporarily unavailable."); } }
  const user = userEvent.setup(); const navigate = vi.fn();
  render(<IncidentWorkspace repository={new FailingReviewRepository()} navigate={navigate} />);
  await user.click(screen.getByRole("tab", { name: "Review" }));
  await user.selectOptions(screen.getByLabelText("Decision"), "REJECTED");
  await user.type(screen.getByLabelText(/Review note/), "Evidence does not support this cause.");
  await user.click(screen.getByRole("button", { name: "Save review" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
  expect(navigate).not.toHaveBeenCalled();
});
