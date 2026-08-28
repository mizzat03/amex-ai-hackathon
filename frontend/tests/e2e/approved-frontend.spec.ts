import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const screenshotRoot = path.resolve(process.cwd(), "..", "docs", "screenshots");
const incidentId = "INC-2026-0827-017";
const captureApprovedBaselines = process.env.AMEX_E2E_LIVE !== "1";

test.skip(process.env.AMEX_E2E_LIVE === "1", "fixture-backed visual and accessibility review");

async function waitForChart(page: Page): Promise<void> {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".recharts-responsive-container svg").first()).toBeVisible();
}

async function expectNoAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

test("captures the approved Overview on desktop and laptop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "8.37%" })).toBeVisible();
  await waitForChart(page);
  if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, "approved-overview-desktop-light.png"), fullPage: false });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "Use dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, "approved-overview-laptop-dark.png"), fullPage: false });
});

test("captures the approved investigation workspace and split pane", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/incidents/${incidentId}`);
  await expect(page.getByRole("heading", { name: /Elevated technical errors/ })).toBeVisible();
  await waitForChart(page);
  if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, "approved-incident-desktop-light.png"), fullPage: false });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "Use dark theme" }).click();
  await page.getByRole("button", { name: "Open Copilot" }).click();
  await expect(page.getByRole("complementary", { name: "Evidence Copilot" })).toBeVisible();
  if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, "approved-incident-laptop-dark.png"), fullPage: false });
});

test("preserves keyboard-safe reset and split-pane controls", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "Reset synthetic demo" }).click();
  await expect(page.getByRole("dialog", { name: "Reset the synthetic demo?" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.goto(`/incidents/${incidentId}`);
  await page.getByRole("button", { name: "Open Copilot" }).click();
  await expect(page.getByRole("complementary", { name: "Evidence Copilot" })).toBeVisible();
  const separator = page.getByRole("separator", { name: "Resize Copilot pane" });
  const widthBefore = Number(await separator.getAttribute("aria-valuenow"));
  await separator.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(separator).toHaveAttribute("aria-valuenow", String(widthBefore + 16));
  await page.getByRole("button", { name: "Close Copilot" }).click();
  await expect(page.getByRole("complementary", { name: "Evidence Copilot" })).toHaveCount(0);

  await page.goto("/fixture-states");
  await expect(page.getByText("Insufficient evidence", { exact: true })).toBeVisible();
  const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(width.scroll).toBeLessThanOrEqual(width.client);
});

test("@a11y has no detectable violations in approved pages or fixture states", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  for (const route of ["/", `/incidents/${incidentId}`, "/fixture-states"]) {
    await page.goto(route);
    await expect(page.locator("main").first()).toBeVisible();
    await expectNoAxeViolations(page);
    const toggle = page.getByRole("button", { name: "Use dark theme" });
    if (await toggle.count()) {
      await toggle.click();
      await expectNoAxeViolations(page);
    }
  }
});
