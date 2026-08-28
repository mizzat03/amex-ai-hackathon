import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OverviewPage } from "@/components/investigator/overview-page";
import { fixtureRepository } from "@/data/repositories/fixture-repository";
import { overviewFixture } from "@/data/fixtures/scenarios";
import { HttpInvestigatorRepository } from "@/data/repositories/http-investigator-repository";

afterEach(() => vi.restoreAllMocks());

it("keeps the approved technical-error punchline and supporting count permanent", () => {
  render(<OverviewPage repository={fixtureRepository} />);
  expect(screen.getByRole("heading", { name: "8.37%" })).toBeVisible();
  expect(screen.getByText("+3,831")).toBeVisible();
  expect(screen.getByText(/Elevated technical errors after authorization deployment/)).toBeVisible();
});

it("requires confirmation before resetting the fixture", async () => {
  const user = userEvent.setup();
  render(<OverviewPage repository={fixtureRepository} />);
  await user.click(screen.getByRole("button", { name: "Reset synthetic demo" }));
  expect(screen.getByRole("dialog", { name: "Reset the synthetic demo?" })).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("never renders incident fixtures while a live clean-state request is loading or complete", async () => {
  const unavailable = (unit: string) => ({
    value: null,
    unit,
    display_precision: null,
    unavailable_reason: "No telemetry yet",
    comparison: null
  });
  const clean = {
    ...overviewFixture,
    generated_at: "2026-08-28T04:00:00Z",
    latest_sample_at: null,
    telemetry_stale_after_seconds: 30,
    telemetry_state: "UNKNOWN",
    baseline: { ready: false, progress: 0, current_samples: 0, required_samples: 1200, unavailable_reason: "No telemetry yet" },
    metrics: {
      approval_rate: unavailable("RATE"),
      business_decline_rate: unavailable("RATE"),
      technical_error_rate: unavailable("RATE"),
      throughput: unavailable("ATTEMPTS_PER_SECOND"),
      average_authorization_latency: unavailable("MILLISECONDS"),
      p95_authorization_latency: unavailable("MILLISECONDS")
    },
    punchline_metric: {
      metric_key: "technical_error_rate",
      label: "Technical error rate",
      metric: unavailable("RATE"),
      supporting_count: unavailable("COUNT")
    },
    active_incident_count: 0,
    active_incidents: []
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/system/overview")) return new Response(JSON.stringify(clean));
    if (url.includes("/metrics/history")) return new Response(JSON.stringify({ metric_key: "technical_error_rate", unit: "RATE", period: { start_at: "2026-08-28T03:25:00Z", end_at: "2026-08-28T04:00:00Z" }, resolution_seconds: 10, points: [], events: [] }));
    if (url.includes("/simulation/status")) return new Response(JSON.stringify({ state: "STOPPED", baseline_ready: false, active_scenario_id: null, started_at: null, available_actions: ["START", "RESET"], message: "No telemetry yet. Start healthy traffic to warm the baseline." }));
    throw new Error(`Unexpected request: ${url}`);
  });

  render(<OverviewPage repository={new HttpInvestigatorRepository("http://example.test/api/v1")} />);

  expect(screen.queryByText("8.37%")).not.toBeInTheDocument();
  expect(await screen.findByText("No telemetry yet.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Start healthy traffic" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Inject regression" })).not.toBeInTheDocument();
});
