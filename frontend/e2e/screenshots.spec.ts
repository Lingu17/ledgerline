import { expect, test, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";

// README screenshots from a real run of the app (throwaway data dir, synthetic sample company).
// Skipped unless SCREENSHOTS=1:  SCREENSHOTS=1 npx playwright test screenshots
const OUT = "../docs/screenshots";
const PASSWORD = `Shot-${randomBytes(9).toString("base64url")}Aa1`;

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to regenerate README screenshots");
test.setTimeout(180_000);

async function shot(page: Page, name: string) {
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

async function runNext(page: Page) {
  // Only the next step has a Run button; it reads "Running…" until the step's request finishes.
  await page.getByRole("button", { name: "Run", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Running…" })).toHaveCount(0, { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
}

test("capture README screenshots", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/#/home");
  await shot(page, "01-landing");
  await page.goto("/#/architecture");
  await page.waitForTimeout(1500);
  await shot(page, "02-architecture");

  await page.goto("/#/signup");
  await page.getByLabel("Your name", { exact: true }).fill("Demo Owner");
  await page.getByLabel("Organization", { exact: true }).fill("Northbeam Software");
  await page.getByLabel("Work email", { exact: true }).fill(`owner-${randomBytes(4).toString("hex")}@shots.test`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByText("Practice company", { exact: true }).click();
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByLabel("Main navigation")).toBeVisible();
  await shot(page, "03-inbox");

  await page.goto("/#/walkthrough");
  await runNext(page); // ask payer agents
  await page.goto("/#/payments?deposit=DEP-1004");
  await shot(page, "04-payment-escalated");
  await page.goto("/#/evidence");
  await shot(page, "05-evidence");
  await page.goto("/#/walkthrough");
  await runNext(page); // cover the EUR bill
  await page.goto("/#/treasury");
  await shot(page, "06-treasury");
  await page.goto("/#/approvals");
  await shot(page, "07-approval");
  await page.getByRole("button", { name: "Approve…" }).click();
  await page.getByRole("button", { name: "Approve this scope" }).click();
  await page.goto("/#/team");
  await page.getByRole("button", { name: "Invite member" }).click();
  await page.getByLabel("Email", { exact: true }).fill(`second-${randomBytes(4).toString("hex")}@shots.test`);
  await page.getByLabel("Role", { exact: true }).selectOption("operator");
  await page.getByRole("button", { name: "Create invitation" }).click();
  const link = await page.getByLabel("Invitation link").inputValue();
  const second = await (await page.context().browser()!.newContext()).newPage();
  await second.goto(link);
  await second.getByLabel("Your name", { exact: true }).fill("Second Member");
  await second.getByLabel(/password/i).fill(PASSWORD);
  await second.getByRole("button", { name: "Join organization" }).click();
  await expect(second.getByLabel("Main navigation")).toBeVisible();
  await second.goto("/#/approvals");
  await second.getByRole("button", { name: "Execute refund" }).click();
  await second.waitForTimeout(1000);
  await page.keyboard.press("Escape");
  await page.goto("/#/walkthrough");
  await runNext(page); // record approval step
  await runNext(page); // SENT
  await runNext(page); // PAID
  await shot(page, "08-walkthrough-done");
  await page.goto("/#/ledger");
  await shot(page, "09-ledger");
  await page.goto("/#/ceo");
  await shot(page, "11-ceo");

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/#/inbox");
  await shot(page, "10-mobile-inbox");
});
