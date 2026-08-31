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

test("verifies the approved Overview on desktop and laptop without rewriting its baselines", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "8.37%" })).toBeVisible();
  await waitForChart(page);

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "Use dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("captures the approved investigation workspace on desktop and laptop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/incidents/${incidentId}`);
  await expect(page.getByRole("heading", { name: /Elevated technical errors/ })).toBeVisible();
  if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, "approved-incident-desktop-light.png"), fullPage: false });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "Use dark theme" }).click();
  if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, "approved-incident-laptop-dark.png"), fullPage: false });
});

test("preserves keyboard-safe reset and incident tab controls", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "Reset synthetic demo" }).click();
  await expect(page.getByRole("dialog", { name: "Reset the synthetic demo?" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.goto(`/incidents/${incidentId}`);
  await page.getByRole("button", { name: "Open Copilot" }).click();
  await expect(page.getByRole("region", { name: "Evidence Copilot" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Copilot" })).toBeFocused();
  await expect(page.getByRole("separator", { name: /Resize Copilot/ })).toHaveCount(0);
  await expect(page.getByText("Reset width")).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Review" })).toBeFocused();

  await page.goto("/fixture-states");
  await expect(page.getByText("Insufficient evidence", { exact: true })).toBeVisible();
  const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(width.scroll).toBeLessThanOrEqual(width.client);
});

test("captures the six approved Copilot states", async ({ page }) => {
  test.setTimeout(90_000);
  const capture = async (state: string, name: string, width: number, height: number, target: string, dark = false): Promise<void> => {
    await page.setViewportSize({ width, height });
    await page.goto(state === "initial" ? `/incidents/${incidentId}` : `/fixture-states?copilot=${state}`);
    if (dark) await page.getByRole("button", { name: "Use dark theme" }).click();
    await page.getByRole("button", { name: "Open Copilot" }).click();
    await expect(page.getByRole("region", { name: "Evidence Copilot" })).toBeVisible();
    const stateTarget = page.getByText(target, { exact: false }).last();
    await expect(stateTarget).toBeVisible();
    await stateTarget.scrollIntoViewIfNeeded();
    if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, name), fullPage: false });
  };

  await capture("initial", "approved-copilot-initial-desktop-light.png", 1440, 1000, "Deployment-aligned authorization failures");
  await capture("follow-up", "approved-copilot-follow-up-desktop-light.png", 1440, 1000, "The timing evidence is strongest; causality remains open");
  await page.goto("/fixture-states?copilot=initial");
  await page.getByRole("button", { name: "Open Copilot" }).click();
  await page.getByLabel("Open citation 1").first().click();
  if (captureApprovedBaselines) await page.screenshot({ path: path.join(screenshotRoot, "approved-copilot-citation-desktop-light.png"), fullPage: false });
  await capture("transition", "approved-copilot-transition-laptop-dark.png", 1280, 800, "Newer incident evidence is available", true);
  await capture("fallback", "approved-copilot-fallback-laptop-dark.png", 1280, 800, "The AI provider is unavailable", true);
  await capture("restored", "approved-copilot-restored-desktop-light.png", 1440, 1000, "The timing evidence is strongest; causality remains open");
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
  await page.goto(`/incidents/${incidentId}`);
  await page.getByRole("button", { name: "Open Copilot" }).click();
  await expectNoAxeViolations(page);
});
