import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IncidentsPage } from "@/components/investigator/incidents-page";
import { fixtureRepository } from "@/data/repositories/fixture-repository";

it("filters incidents by severity and supports an empty search state", async () => {
  const user = userEvent.setup();
  render(<IncidentsPage repository={fixtureRepository} />);
  await user.selectOptions(screen.getByLabelText("Filter severity"), "HIGH");
  expect(screen.getAllByText("HIGH").length).toBeGreaterThan(0);
  expect(screen.queryByText("Issuer latency elevated in AU card-present traffic")).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("Search incidents"), "no-such-incident");
  expect(screen.getByText("No incidents match these filters.")).toBeVisible();
});

it("restores list controls and highlights the incident returned from review", async () => {
  window.history.replaceState({}, "", "/incidents?severity=HIGH&sort=desc&reviewed=INC-2026-0827-017");
  sessionStorage.setItem("amex:review-success", "Review saved as acknowledged version 2.");

  render(<IncidentsPage repository={fixtureRepository} />);

  expect(screen.getByLabelText("Filter severity")).toHaveValue("HIGH");
  expect(screen.getByRole("button", { name: "Started newest" })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Review saved as acknowledged");
  expect(await screen.findByText("Review updated")).toBeVisible();
});
