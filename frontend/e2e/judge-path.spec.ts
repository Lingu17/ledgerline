import { expect, test, type Page } from "@playwright/test";

/** The path a judge takes, end to end, at desktop width and at 375 px: one-click demo → DEP-1005 (verified, becomes
 *  credit) → DEP-1004 (signed but false, rejected) → /attacks → /evidence → CEO view. Fails on any console error, any
 *  request that fails, any response of 400 or more, and any sideways scroll. */

function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("requestfailed", (r) => {
    const why = r.failure()?.errorText ?? "";
    if (!/ERR_ABORTED|NS_BINDING_ABORTED/.test(why)) problems.push(`request failed: ${r.method()} ${r.url()} ${why}`);
  });
  page.on("response", (r) => { if (r.status() >= 400) problems.push(`HTTP ${r.status()}: ${r.request().method()} ${r.url()}`); });
  return problems;
}

async function noSidewaysScroll(page: Page, where: string) {
  const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll, `sideways scroll on ${where}`).toBeLessThanOrEqual(inner + 1);
}

for (const size of [{ name: "desktop", width: 1280, height: 800 }, { name: "phone 375", width: 375, height: 812 }]) {
  test(`judge path, ${size.name}: one click, DEP-1005, DEP-1004, attacks, evidence, CEO view`, async ({ browser }) => {
    test.setTimeout(120_000);
    const context = await browser.newContext({ viewport: { width: size.width, height: size.height } });
    const page = await context.newPage();
    const problems = watch(page);

    await page.goto("/");
    await page.getByRole("button", { name: "Judge demo — one click" }).click();
    await expect(page.getByLabel("Main navigation")).toBeAttached({ timeout: 20_000 });
    await expect(page.getByText("DEP-1005").first()).toBeVisible();
    await noSidewaysScroll(page, "inbox");

    const ask = async (id: string, expected: RegExp) => {
      await page.goto(`/#/payments?deposit=${id}`);
      await page.getByRole("button", { name: /Ask payer's agent/ }).first().click();
      await expect(page.locator(".drawer").getByText(expected).first()).toBeVisible({ timeout: 25_000 });
      await page.waitForLoadState("networkidle");
      await noSidewaysScroll(page, id);
    };
    await ask("DEP-1005", /Held as credit/);
    await expect(page.locator(".drawer").getByText("Verified", { exact: true }).first()).toBeVisible();
    await ask("DEP-1004", /Needs review/);

    await page.goto("/attacks");
    const score = page.getByTestId("attack-score");
    await expect(score).toHaveText(/(\d+)\/\1 blocked · \$0 moved/);
    await expect(page.getByText("Not blocked")).toHaveCount(0);
    await noSidewaysScroll(page, "/attacks");

    await page.goto("/evidence");
    await expect(page.getByText("Refund, SENT → PAID").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Simulated only" })).toBeVisible();
    await noSidewaysScroll(page, "/evidence");

    await page.goto("/#/ceo");
    await expect(page.getByRole("heading", { name: /Are we safe/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "What the agent handled" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await noSidewaysScroll(page, "CEO view");

    expect(problems, problems.join("\n")).toEqual([]);
    await context.close();
  });
}
