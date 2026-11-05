import { expect, test, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";

const PASSWORD = `Audit-${randomBytes(9).toString("base64url")}Aa1`;
const uniq = () => randomBytes(4).toString("hex");
const PAGES = ["ceo", "inbox", "payments", "approvals", "evidence", "treasury", "ledger", "customers", "activity", "team", "settings", "walkthrough", "architecture"];
const problems: string[] = [];
const done: string[] = [];
test.setTimeout(420_000);
test.use({ actionTimeout: 8000 });

function watch(page: Page, who: string) {
  page.on("console", (m) => { if (m.type() === "error" && !/status of 4(01|03|09|22)/.test(m.text())) problems.push(`[console ${who}] ${page.url().split("#")[1]}: ${m.text().slice(0, 200)}`); });
  page.on("pageerror", (e) => problems.push(`[crash ${who}] ${page.url().split("#")[1]}: ${e.message.slice(0, 200)}`));
  page.on("response", (r) => { if (r.status() >= 500) problems.push(`[http ${r.status()} ${who}] ${r.url().split("8765")[1]}`); });
}

async function step(name: string, fn: () => Promise<void>) {
  try { await fn(); done.push(name); } catch (e) { problems.push(`[FAILED] ${name}: ${String(e).split("\n").slice(0, 3).join(" ").slice(0, 260)}`); }
}

async function scan(page: Page, label: string) {
  for (const p of PAGES) {
    await page.goto(`/#/${p}`);
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(250);
    // A page that is still drawing is not a blank page: give it up to 5 s to show content before judging it.
    await page.waitForFunction(() => (document.querySelector("main") ?? document.body).innerText.length >= 20, null, { timeout: 5000 }).catch(() => {});
    const r = await page.evaluate(() => {
      const t = (document.querySelector("main") ?? document.body).innerText;
      const bad = t.match(/undefined|NaN|\[object|\bnull\b|Infinity|Traceback|Internal Server Error/g);
      return { bad: bad ? [...new Set(bad)] : [], over: document.documentElement.scrollWidth - window.innerWidth, len: t.length,
        broken: [...document.images].filter((i) => i.complete && !i.naturalWidth).length };
    });
    if (r.bad.length) problems.push(`[text ${label}] ${p}: ${r.bad.join(",")}`);
    if (r.over > 0) problems.push(`[overflow ${label}] ${p}: ${r.over}px`);
    if (r.len < 20) problems.push(`[blank ${label}] ${p}: ${r.len} chars`);
    if (r.broken) problems.push(`[image ${label}] ${p}: ${r.broken}`);
  }
}

// One long journey as real people: two members, every page on desktop and phone, no crash, server error or broken text.
test("full journey as two people", async ({ page, browser }) => {
  page.setDefaultTimeout(8000);
  expect.configure({ timeout: 8000 });
  watch(page, "owner");
  await page.setViewportSize({ width: 1366, height: 800 });
  await step("landing, sign-in and sign-up pages open", async () => {
    for (const h of ["#/home", "#/login", "#/signup", "#/architecture"]) { await page.goto(`/${h}`); await page.waitForLoadState("networkidle"); }
  });
  const email = `owner-${uniq()}@audit.test`;
  await step("create a practice company", async () => {
    await page.goto("/#/signup");
    await page.getByLabel("Your name", { exact: true }).fill("Audit Owner");
    await page.getByLabel("Organization", { exact: true }).fill(`Audit ${uniq()}`);
    await page.getByLabel("Work email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByText("Practice company", { exact: true }).click();
    await page.getByRole("button", { name: "Create organization" }).click();
    await expect(page.getByLabel("Main navigation")).toBeVisible();
  });
  await step("every page, fresh company, desktop", () => scan(page, "desktop-fresh"));

  const ask = async (id: string, expected: RegExp) => {
    await page.goto(`/#/payments?deposit=${id}`);
    await page.getByRole("button", { name: /Ask payer's agent/ }).first().click();
    await expect(page.locator(".drawer").getByText(expected).first()).toBeVisible({ timeout: 25_000 });
    await page.waitForLoadState("networkidle");
  };
  await step("DEP-1005 duplicate becomes credit", () => ask("DEP-1005", /Held as credit/));
  await step("DEP-1004 false claim rejected", () => ask("DEP-1004", /Needs review/));
  await step("DEP-1006 real duplicate needs approval", () => ask("DEP-1006", /Refund for approval/));
  await step("read remittance on DEP-1004", async () => {
    await page.goto("/#/payments?deposit=DEP-1004");
    await page.getByRole("button", { name: /Read remittance/ }).click();
    const drawer = page.locator(".drawer");
    await drawer.locator("textarea").first().fill("Hello, we paid EUR 1,750 for invoice INV-2253 for Brightwave as their reseller.");
    await drawer.getByRole("button", { name: "Read text" }).click();
    await expect(drawer.getByText(/advisory|suggests/i).first()).toBeVisible({ timeout: 20_000 });
    // Resolve starts from what the reading suggested (or says why it cannot); nothing is recorded until a person does it.
    // The reading must be on the payment before Resolve can start from it (a slow machine reloads it later).
    await expect(drawer.getByText(/Remittance read by/).first()).toBeVisible({ timeout: 20_000 });
    await drawer.getByRole("button", { name: "Resolve…" }).click();
    await expect(drawer.getByText(/remittance reading \(EV-DEP-1004-/).first()).toBeVisible({ timeout: 20_000 });
    await drawer.getByRole("button", { name: "Cancel" }).click();
  });
  await step("balance request email draft on DEP-1003", async () => {
    await page.goto("/#/payments?deposit=DEP-1003");
    await expect(page.getByRole("link", { name: "Open email draft" })).toBeVisible();
    await expect(page.getByText("Next:", { exact: true })).toBeVisible();
  });

  const opEmail = `op-${uniq()}@audit.test`;
  const opCtx = await browser.newContext({ viewport: { width: 1366, height: 800 } });
  const op = await opCtx.newPage();
  op.setDefaultTimeout(8000);
  watch(op, "operator");
  await step("invite and join a second person", async () => {
    await page.goto("/#/team");
    await page.getByRole("button", { name: "Invite member" }).click();
    await page.getByLabel("Email", { exact: true }).fill(opEmail);
    await page.getByLabel("Role", { exact: true }).selectOption("operator");
    await page.getByRole("button", { name: "Create invitation" }).click();
    const link = await page.getByLabel("Invitation link").inputValue();
    await page.keyboard.press("Escape");
    await op.goto(link);
    await op.getByLabel("Your name", { exact: true }).fill("Audit Operator");
    await op.getByLabel(/password/i).fill(PASSWORD);
    await op.getByRole("button", { name: "Join organization" }).click();
    await expect(op.getByLabel("Main navigation")).toBeVisible();
  });

  await step("refund: one person approves, cannot also send, another sends, SENT, PAID", async () => {
    await op.goto("/#/approvals");
    await op.getByRole("button", { name: "Approve…" }).click();
    await op.getByRole("button", { name: "Approve this scope" }).click();
    await expect(op.getByText(/so you can't also send it/)).toBeVisible();
    await expect(op.getByRole("button", { name: "Execute refund" })).toHaveCount(0);
    await page.goto("/#/approvals");
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.getByRole("button", { name: "Execute refund" }).click();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /: sent$/ }).first().click();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /: paid$/ }).first().click();
    await expect(page.getByText("paid", { exact: false }).first()).toBeVisible();
  });

  await step("cash squeeze, bill payment by two people to PAID", async () => {
    await page.goto("/#/treasury");
    await page.getByRole("button", { name: "Add a cash squeeze" }).click();
    await expect(page.locator(".pill", { hasText: "Escalate" }).first()).toBeVisible();
    await page.getByRole("button", { name: "Pay", exact: true }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Propose payment" }).click();
    await expect(page.getByText("Needs a second person")).toBeVisible();
    await op.goto("/#/approvals");
    await op.evaluate(() => window.dispatchEvent(new Event("focus")));
    await op.getByRole("button", { name: "Approve", exact: true }).click();
    await op.getByRole("button", { name: "Send payment" }).click();
    await op.getByRole("button", { name: "Simulate bank: sent" }).click();
    await op.getByRole("button", { name: "Simulate bank: paid" }).click();
    await op.waitForLoadState("networkidle");
    await op.goto("/#/treasury");
    await expect(op.locator(".pill", { hasText: /^paid$/i }).first()).toBeVisible();
  });
  await step("early-payment offer paid, bills re-planned", async () => {
    await page.goto("/#/treasury");
    await page.getByRole("button", { name: "Create offer" }).first().click();
    await page.getByRole("button", { name: "Practice: customer pays" }).click();
    await expect(page.getByText("Practice payment received")).toBeVisible();
  });
  await step("replay a plan", async () => {
    await page.getByRole("button", { name: "Replay", exact: true }).first().click();
    await expect(page.getByText("Replay identical")).toBeVisible();
  });
  await step("a new unclear payment is handled with no further click", async () => {
    await page.goto("/#/payments");
    await page.getByRole("button", { name: "Receive an unclear payment" }).click();
    await expect(page.getByText(/agent handled it with no click/)).toBeVisible({ timeout: 25_000 });
    // The CEO view tells the same story from the audit log: asked with no click, checked, placed.
    await page.goto("/#/ceo");
    const panel = page.locator(".card", { has: page.getByRole("heading", { name: "What the agent did by itself" }) });
    await expect(panel.getByText("No click").first()).toBeVisible({ timeout: 15_000 });
    await expect(panel.getByText(/Asked the payer's agent, with no click → Checked the signed answer: 3 of 3 checks passed/).first()).toBeVisible();
  });
  await step("wrong-currency payment converted", async () => {
    await page.goto("/#/payments");
    await page.getByRole("button", { name: "Add a wrong-currency payment" }).click();
    // The unclear payment added above is also a practice payment, so pick this one by its own bank reference, and
    // wait until the request that adds it has finished.
    const findId = () => page.evaluate(async () => ((await (await fetch("/api/deposits?limit=200")).json()) as { id: string; provider_ref: string }[]).find((x) => x.provider_ref === "PRACTICE-FX-1")?.id ?? "");
    await expect.poll(findId, { timeout: 15_000 }).not.toBe("");
    const id = await findId();
    await page.goto(`/#/payments?deposit=${id}`);
    await expect(page.getByRole("heading", { name: "Paid in the wrong currency" })).toBeVisible();
    await page.getByRole("button", { name: "Convert and apply" }).click();
    await page.waitForLoadState("networkidle");
  });
  await step("pause blocks, owner resumes", async () => {
    await page.goto("/#/settings");
    await expect(page.getByRole("button", { name: "Pause all money-out" })).toBeDisabled();  // a reason first
    await page.getByLabel("Reason for pausing").fill("Audit check");
    await page.getByRole("button", { name: "Pause all money-out" }).click();
    const reason = page.getByRole("dialog").locator("input,textarea").first();
    if (await reason.count()) { await reason.fill("Audit check"); await page.getByRole("dialog").getByRole("button", { name: /pause/i }).click(); }
    await expect(page.getByRole("button", { name: "Resume money-out" })).toBeVisible();
    await page.getByRole("button", { name: "Resume money-out" }).click();
    const resumeDialog = page.getByRole("dialog");
    if (await resumeDialog.count()) await resumeDialog.getByRole("button", { name: /resume/i }).click();
    await expect(page.getByRole("button", { name: "Pause all money-out" })).toBeVisible();
  });
  await step("save policy", async () => {
    await page.goto("/#/settings");
    await page.getByRole("button", { name: "Save policy" }).click();
    await page.waitForLoadState("networkidle");
  });
  await step("new customer", async () => {
    await page.goto("/#/customers");
    await page.getByRole("button", { name: "New customer" }).first().click();
    const c = page.getByRole("dialog");
    await c.getByLabel(/name/i).first().fill("Audit Customer Ltd");
    await c.getByLabel(/country/i).first().fill("GB");
    await c.getByLabel(/payer|remitter/i).first().fill("AUDIT CUSTOMER LTD");
    await c.getByLabel(/refund|account/i).first().fill("Audit account");
    await c.getByRole("button", { name: /save|create|add/i }).last().click();
    await page.waitForLoadState("networkidle");
  });
  await step("activity: verify log and download evidence", async () => {
    await page.goto("/#/activity");
    await page.getByRole("button", { name: "Verify log integrity" }).click();
    await expect(page.getByText("Log intact.")).toBeVisible();
    const d = page.waitForEvent("download", { timeout: 10_000 });
    await page.getByRole("button", { name: /Download evidence/ }).or(page.getByRole("link", { name: /Download evidence/ })).first().click();
    await d;
  });
  await step("books still balance after everything", async () => {
    const r = await page.evaluate(async () => {
      const l = await (await fetch("/api/ledger")).json();
      const v = await (await fetch("/api/audit/verify")).json();
      const c = await (await fetch("/api/ceo")).json();
      return { b: l.conservation.all_balanced, v: v.ok, d: c.trust.double_payments };
    });
    expect(r).toEqual({ b: true, v: true, d: 0 });
  });
  await step("every page after full use, desktop", () => scan(page, "desktop-used"));
  await page.setViewportSize({ width: 375, height: 812 });
  await step("every page after full use, phone", () => scan(page, "phone-used"));
  await page.setViewportSize({ width: 1366, height: 800 });
  await step("sign out and back in", async () => {
    await page.goto("/#/inbox");
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByLabel("Work email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByLabel("Main navigation")).toBeVisible();
  });
  await step("a brand-new empty company, every page", async () => {
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 800 } });
    const p = await ctx.newPage();
    p.setDefaultTimeout(8000);
    watch(p, "empty");
    await p.goto("/#/signup");
    await p.getByLabel("Your name", { exact: true }).fill("Empty Owner");
    await p.getByLabel("Organization", { exact: true }).fill(`Empty ${uniq()}`);
    await p.getByLabel("Work email", { exact: true }).fill(`e-${uniq()}@audit.test`);
    await p.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await p.getByRole("button", { name: "Create organization" }).click();
    await expect(p.getByLabel("Main navigation")).toBeVisible();
    await scan(p, "empty");
    await ctx.close();
  });
  await opCtx.close();
  expect(problems).toEqual([]);
  expect(done.length).toBeGreaterThanOrEqual(24);
});
