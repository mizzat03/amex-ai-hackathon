import { expect, test } from "@playwright/test";

test.skip(process.env.AMEX_E2E_LIVE !== "1", "requires the local PostgreSQL/Redis/API stack");

test("complete judge path remains useful through deterministic AI fallback", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/");
  const reset = page.getByRole("button", { name: "Reset synthetic demo" });
  const stop = page.getByRole("button", { name: "Stop simulation" });
  await expect.poll(async () => await reset.isVisible() || await stop.isVisible()).toBe(true);
  if (!(await reset.isVisible())) await stop.click();
  await expect(reset).toBeVisible();
  await reset.click();
  await page.getByRole("button", { name: "Confirm reset" }).click();
  await expect(page.getByRole("heading", { name: "No telemetry yet." })).toBeVisible();

  await page.getByRole("button", { name: "Start healthy traffic" }).click();
  await expect(page.getByRole("button", { name: "Inject regression" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Inject regression" }).click();
  await expect(page.getByText("incident active", { exact: true })).toBeVisible();

  await expect(page.getByRole("link", { name: "Open investigation" })).toBeVisible({ timeout: 40_000 });
  await page.getByRole("link", { name: "Open investigation" }).click();
  await expect(page.getByRole("heading", { name: /Elevated technical errors/ })).toBeVisible();
  await page.getByRole("button", { name: "Open Copilot" }).click();
  await expect(page.getByRole("region", { name: "Evidence Copilot" })).toBeVisible();
  await page.getByLabel("Ask about this incident evidence").fill("What evidence weakens this hypothesis?");
  await page.getByRole("button", { name: "Submit question" }).click();
  await expect(page.getByText("Deterministic fallback", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/provider_disabled|evidence_unavailable/)).toHaveCount(0);

  await page.getByRole("tab", { name: "Review" }).click();
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(page).toHaveURL(/\/incidents\?.*reviewed=/);
  await expect(page.getByText("Review updated")).toBeVisible();

  await page.goto("/");
  await page.getByRole("button", { name: "Trigger rollback" }).click();
  await expect(page.getByText("recovering", { exact: true })).toBeVisible();
});
