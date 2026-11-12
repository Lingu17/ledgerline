import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";

/** The whole judge path on a running site with ONE press of "Judge demo — one click": DEP-1005 refund → credit,
 *  DEP-1004 rejected with its reason, the over-limit refund approved by Judge A and sent by Teammate B, SENT → PAID on
 *  the simulated bank, the CEO view, /attacks and /evidence. Walked at desktop width, then every screen again at 375 px
 *  in the same demo company. Fails on any console error, failed request, response of 400 or more, or sideways scroll.
 *  Screenshots go to SHOTS (default docs/live-check). */
const SHOTS = process.env.SHOTS || "../docs/live-check";

test("live judge path, one button press, desktop then 375 px", async ({ browser }) => {
  mkdirSync(SHOTS, { recursive: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const problems: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("requestfailed", (r) => { if (!/ERR_ABORTED|NS_BINDING_ABORTED/.test(r.failure()?.errorText ?? "")) problems.push(`failed: ${r.url()}`); });
  page.on("response", (r) => { if (r.status() >= 400) problems.push(`HTTP ${r.status()}: ${r.request().method()} ${r.url()}`); });
  let width = "desktop";
  const shot = async (name: string) => {
    const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(scroll, `sideways scroll on ${name} (${width})`).toBeLessThanOrEqual(inner + 1);
    await page.screenshot({ path: `${SHOTS}/${width}-${name}.png`, fullPage: true });
  };
  const drawer = page.locator(".drawer");
  const openPayment = async (id: string) => {
    await page.goto(`/#/payments?deposit=${id}`);
    await expect(drawer.getByText(id).first()).toBeVisible({ timeout: 20_000 });
  };
  const row = (title: string) => page.locator(".steps li").filter({ hasText: title });
  const finish = async (title: string) => {
    await expect(row(title)).toBeVisible({ timeout: 20_000 });
    if ((await row(title).locator(".n.done").count()) === 0) await row(title).getByRole("button", { name: "Run", exact: true }).click();
    await expect(row(title).locator(".n.done")).toHaveCount(1, { timeout: 30_000 });
  };

  // 1. One press.
  await page.goto("/");
  await shot("01-landing");
  await page.getByRole("button", { name: "Judge demo — one click" }).click();
  await expect(page.getByText("You are Judge A (Owner)")).toBeVisible({ timeout: 30_000 });
  await shot("02-inbox-as-judge-a");

  // 2. DEP-1005: the first plan holds a refund; the signed answer turns it into credit.
  await openPayment("DEP-1005");
  await page.getByRole("button", { name: /Ask payer's agent/ }).first().click();
  await expect(drawer.getByText(/Held as credit/).first()).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByText("Verified", { exact: true }).first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot("03-dep-1005-credit");

  // 3. DEP-1004: signed but false; rejected and sent to a person with the reason.
  await openPayment("DEP-1004");
  await page.getByRole("button", { name: /Ask payer's agent/ }).first().click();
  await expect(drawer.getByText(/Needs review/).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await shot("04-dep-1004-rejected");

  // 4. The rest of the practice story, up to the over-limit refund.
  await page.goto("/#/walkthrough");
  for (const t of ["Receive six deposits", "Request the short balance", "Ask payer agents", "Cover the EUR bill"]) await finish(t);

  // 5. Judge A approves the agent-proposed refund, and is told they cannot also send it.
  await page.goto("/#/approvals");
  await page.getByRole("button", { name: "Approve…" }).first().click();
  await page.getByRole("button", { name: "Approve this scope" }).click();
  await expect(page.getByText(/so you can't also send it/)).toBeVisible({ timeout: 20_000 });
  await shot("05-approved-by-judge-a");

  // 6. Teammate B sends it.
  await page.getByRole("button", { name: "Switch to Teammate B" }).click();
  await expect(page.getByText("You are Teammate B (Operator)")).toBeVisible({ timeout: 20_000 });
  await page.goto("/#/approvals");
  await page.getByRole("button", { name: "Execute refund" }).first().click();
  await expect(page.getByText("Sending…")).toHaveCount(0, { timeout: 30_000 });
  await page.reload();
  await expect(page.getByText("Money-out operations")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Execute refund" })).toHaveCount(0);
  await expect(page.locator("table").getByText(/refund/i).first()).toBeVisible({ timeout: 20_000 });
  await page.waitForLoadState("networkidle");
  await shot("06-sent-by-teammate-b");

  // 7. The simulated bank reports SENT, then PAID (Judge A runs the practice steps).
  await page.getByRole("button", { name: "Switch to Judge A" }).click();
  await expect(page.getByText("You are Judge A (Owner)")).toBeVisible({ timeout: 20_000 });
  await page.goto("/#/walkthrough");
  for (const t of ["Approve and send the refund", "Bank reports SENT", "Bank reports PAID"]) await finish(t);
  await shot("07-sent-then-paid");

  // 8. CEO view, including what the agent did by itself.
  await page.goto("/#/ceo");
  await expect(page.getByRole("heading", { name: "What the agent handled" })).toBeVisible({ timeout: 20_000 });
  await page.waitForLoadState("networkidle");
  await shot("08-ceo-view");

  // 9. Public pages.
  await page.goto("/attacks");
  await expect(page.getByTestId("attack-score")).toHaveText(/(\d+)\/\1 blocked · \$0 moved/, { timeout: 20_000 });
  await shot("09-attacks");
  await page.goto("/evidence");
  await expect(page.getByText("Refund, SENT → PAID").first()).toBeVisible({ timeout: 20_000 });
  await shot("10-evidence");

  // The same screens at 375 px, in the same demo company (no second press).
  width = "375";
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await shot("01-landing");
  await page.goto("/#/inbox");
  await expect(page.getByRole("button", { name: "Switch to Teammate B" })).toBeVisible({ timeout: 20_000 });
  await shot("02-inbox");
  await openPayment("DEP-1005");
  await expect(drawer.getByText(/Held as credit/).first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot("03-dep-1005-credit");
  await openPayment("DEP-1004");
  await expect(drawer.getByText(/Needs review/).first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot("04-dep-1004-rejected");
  await page.goto("/#/walkthrough");
  await expect(row("Bank reports PAID").locator(".n.done")).toHaveCount(1, { timeout: 20_000 });
  await shot("07-sent-then-paid");
  await page.goto("/#/ceo");
  await expect(page.getByRole("heading", { name: "What the agent handled" })).toBeVisible({ timeout: 20_000 });
  await page.waitForLoadState("networkidle");
  await shot("08-ceo-view");
  await page.goto("/attacks");
  await expect(page.getByTestId("attack-score")).toHaveText(/(\d+)\/\1 blocked · \$0 moved/, { timeout: 20_000 });
  await shot("09-attacks");
  await page.goto("/evidence");
  await expect(page.getByText("Refund, SENT → PAID").first()).toBeVisible({ timeout: 20_000 });
  await shot("10-evidence");

  expect(problems, problems.join("\n")).toEqual([]);
  await context.close();
});
