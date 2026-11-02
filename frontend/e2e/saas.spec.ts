import { expect, test, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";

// Generated per run; never stored. Meets the 12+ chars / upper / lower / digit policy.
const PASSWORD = `E2e-${randomBytes(9).toString("base64url")}Aa1`;
const uniq = () => randomBytes(4).toString("hex");

async function signUp(page: Page, opts: { org: string; email: string; sample: boolean }) {
  await page.goto("/#/signup");
  await page.getByLabel("Your name", { exact: true }).fill("E2E Owner");
  await page.getByLabel("Organization", { exact: true }).fill(opts.org);
  await page.getByLabel("Work email", { exact: true }).fill(opts.email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  if (opts.sample) await page.getByText("Practice company", { exact: true }).click();
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("navigation", { name: "Main navigation" }).or(page.getByLabel("Main navigation"))).toBeVisible();
}

async function nav(page: Page, label: string) {
  await page.getByLabel("Main navigation").getByRole("link", { name: label, exact: false }).first().click();
}

test("sign up with sample data, sign out, sign back in", async ({ page }) => {
  const email = `owner-${uniq()}@e2e.test`;
  await signUp(page, { org: `Sample ${uniq()}`, email, sample: true });
  await expect(page.getByLabel("Main navigation").getByText("Practice steps")).toBeVisible();
  await nav(page, "Payments");
  await expect(page.getByText("DEP-1001").first()).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  // The old session is gone server-side, not just in the UI.
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);

  await page.getByLabel("Work email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByLabel("Main navigation")).toBeVisible();
});

test("home page explains the product and leads to sign-up", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Every incoming payment");
  for (const id of ["how", "features", "safety", "faq"]) await expect(page.locator(`#${id}`)).toBeAttached();
  await page.getByRole("link", { name: "How it works" }).first().click();
  await expect(page).toHaveURL(/#\/?$|\/$/);  // section links scroll; they do not change the route
  await expect(page.locator("#how")).toBeInViewport();
  await page.getByRole("link", { name: "Get started" }).click();
  await expect(page.getByRole("heading", { name: "Create your organization" })).toBeVisible();
  await page.getByRole("link", { name: "Ledgerline home" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Every incoming payment");
});

test("Google sign-in explains missing credentials and Apple is absent from the login form", async ({ page }) => {
  await page.goto("/#/signin");
  const google = page.getByRole("button", { name: "Continue with Google" });
  const apple = page.getByRole("button", { name: "Continue with Apple" });
  await expect(google).toBeDisabled();
  await expect(apple).toHaveCount(0);
  await expect(page.getByText("have not been set up by this server's administrator")).toBeVisible();
  await page.screenshot({ path: "test-results/signin-oauth.png" });
  // A provider error coming back from the server is explained on the sign-in page.
  await page.goto("/#/signin?oauth_error=account_exists");
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Sign in with your password, then connect it");
});

test("settings lists sign-in methods", async ({ page }) => {
  await signUp(page, { org: `Methods ${uniq()}`, email: `sm-${uniq()}@e2e.test`, sample: false });
  await page.goto("/#/settings");
  const card = page.locator(".card", { hasText: "Sign-in methods" });
  await expect(card.getByText("Email and password")).toBeVisible();
  await expect(card.getByText("Not set up on this server")).toHaveCount(1);
  await expect(card.getByText("Apple")).toHaveCount(0); // not offered, so no row that looks unfinished
  await card.screenshot({ path: "test-results/signin-methods.png" });
});

test("wrong password is refused without revealing whether the account exists", async ({ page }) => {
  await page.goto("/#/signin");
  await page.getByLabel("Work email", { exact: true }).fill(`nobody-${uniq()}@e2e.test`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText(/incorrect|invalid/i);
});

test("empty workspace: record a manual payment through the form", async ({ page }) => {
  await signUp(page, { org: `Empty ${uniq()}`, email: `ops-${uniq()}@e2e.test`, sample: false });
  await expect(page.getByLabel("Main navigation").getByText("Practice steps")).toHaveCount(0);
  await nav(page, "Payments");
  await page.getByRole("button", { name: "Record payment" }).click();
  const ref = `BANK-${uniq()}`;
  await page.getByLabel("Statement reference", { exact: true }).fill(ref);
  await page.getByLabel("Amount", { exact: true }).fill("125.50");
  await page.getByLabel("Remitter name", { exact: true }).fill("UNKNOWN PAYER LTD");
  await page.getByRole("dialog").getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByText(/Recorded DEP-/)).toBeVisible();
  await expect(page.getByText("UNKNOWN PAYER LTD").first()).toBeVisible();
});

test("invited viewer is read-only in the UI and refused by the API", async ({ page, browser }) => {
  await signUp(page, { org: `Team ${uniq()}`, email: `owner-${uniq()}@e2e.test`, sample: true });
  await nav(page, "Team");
  await page.getByRole("button", { name: "Invite member" }).click();
  const viewerEmail = `viewer-${uniq()}@e2e.test`;
  await page.getByLabel("Email", { exact: true }).fill(viewerEmail);
  await page.getByLabel("Role", { exact: true }).selectOption("viewer");
  await page.getByRole("button", { name: "Create invitation" }).click();
  const link = await page.getByLabel("Invitation link").inputValue();
  expect(link).toContain("invite");

  const viewerCtx = await browser.newContext();
  const viewer = await viewerCtx.newPage();
  await viewer.goto(link);
  await viewer.getByLabel("Your name", { exact: true }).fill("E2E Viewer");
  await viewer.getByLabel(/password/i).fill(PASSWORD);
  await viewer.getByRole("button", { name: "Join organization" }).click();
  await expect(viewer.getByText("Read-only", { exact: true })).toBeVisible();
  await nav(viewer, "Payments");
  await expect(viewer.getByText("DEP-1001").first()).toBeVisible();
  await expect(viewer.getByRole("button", { name: "Record payment" })).toHaveCount(0);
  await expect(viewer.getByRole("button", { name: "Import CSV" })).toHaveCount(0);

  // Hidden buttons are not the control: the API refuses a viewer's mutation too.
  const csrf = await viewer.evaluate(async () => (await (await fetch("/api/auth/me")).json()).csrf_token);
  const r = await viewer.request.post("/api/payments", {
    headers: { "X-CSRF-Token": csrf, Origin: new URL(link).origin },
    data: { external_ref: "X-1", currency: "GBP", amount: "1.00", payer_name: "X" },
  });
  expect(r.status()).toBe(403);
  await viewerCtx.close();
});

test("a second organization cannot see the first organization's payments", async ({ page, browser }) => {
  await signUp(page, { org: `Alpha ${uniq()}`, email: `a-${uniq()}@e2e.test`, sample: true });
  await nav(page, "Payments");
  await expect(page.getByText("DEP-1006").first()).toBeVisible();

  const otherCtx = await browser.newContext();
  const other = await otherCtx.newPage();
  await signUp(other, { org: `Beta ${uniq()}`, email: `b-${uniq()}@e2e.test`, sample: false });
  await nav(other, "Payments");
  await expect(other.getByText("DEP-1006")).toHaveCount(0);
  expect((await other.request.get("/api/deposits/DEP-1006")).status()).toBe(404);
  await otherCtx.close();
});

test("phone width: no page-level horizontal overflow", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await signUp(page, { org: `Mobile ${uniq()}`, email: `m-${uniq()}@e2e.test`, sample: true });
  for (const hash of ["#/home", "#/inbox", "#/payments", "#/treasury", "#/customers", "#/team", "#/settings"]) {
    await page.goto(`/${hash}`);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${hash} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
  }
  await ctx.close();
});

test("sign-up says which field is missing", async ({ page }) => {
  await page.goto("/#/signup");
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("alert")).toHaveText("Enter your name.");
  await page.getByLabel("Your name", { exact: true }).fill("E2E Owner");
  await page.getByLabel("Organization", { exact: true }).fill("Acme");
  await page.getByLabel("Work email", { exact: true }).fill(`v-${uniq()}@e2e.test`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("alert")).toContainText("password of at least 12 characters");
});

test("a real company sees setup steps and short-cash decisions", async ({ page }) => {
  await signUp(page, { org: `Real ${uniq()}`, email: `r-${uniq()}@e2e.test`, sample: false });
  await expect(page.getByRole("heading", { name: "Set up your company" })).toBeVisible();
  await page.goto("/#/treasury");
  await page.getByRole("button", { name: "Add bill" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Payee").fill("November payroll");
  await dialog.getByLabel("Amount").fill("9000");
  await dialog.getByLabel("Due date").fill(new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10));
  await dialog.getByLabel("Priority").selectOption("critical");
  await dialog.getByRole("button", { name: "Add bill" }).click();
  await expect(page.getByRole("heading", { name: "What to pay first" })).toBeVisible();
  await expect(page.locator(".pill", { hasText: "Escalate" }).first()).toBeVisible();
  await page.screenshot({ path: "test-results/treasury-decisions.png", fullPage: true });
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { name: "Connect your Airwallex account" })).toBeVisible();
});

test("practice company shows all four cash decisions", async ({ page }) => {
  await signUp(page, { org: `Squeeze ${uniq()}`, email: `q-${uniq()}@e2e.test`, sample: true });
  await page.goto("/#/treasury");
  await page.getByRole("button", { name: "Add a cash squeeze" }).click();
  for (const label of ["Fund", "Convert", "Defer", "Escalate"]) await expect(page.locator(".pill", { hasText: label }).first()).toBeVisible();
  await page.getByRole("button", { name: "Pay", exact: true }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Propose payment" }).click();
  await expect(page.getByText("Needs a second person")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeDisabled(); // the proposer cannot approve
  await page.goto("/#/approvals"); // the sidebar count leads here, so the payment has to be here too
  await expect(page.getByText("Needs a second person")).toBeVisible();
  await expect(page.getByText("No approvals waiting")).toHaveCount(0);
  await page.goto("/#/treasury");
  await page.getByRole("button", { name: "Create offer" }).first().click();
  await page.getByRole("button", { name: "Practice: customer pays" }).click();
  await expect(page.getByText("Practice payment received")).toBeVisible();
  await page.getByRole("button", { name: "Replay", exact: true }).first().click();
  await expect(page.getByText("Replay identical")).toBeVisible();
  await page.screenshot({ path: "test-results/cash-squeeze.png", fullPage: true });
  await page.goto("/#/activity");
  await page.getByRole("button", { name: "Verify log integrity" }).click();
  await expect(page.getByText("Log intact.")).toBeVisible();
});

test("wrong-currency payment converts only what the invoice needs; balance request has an email draft", async ({ page }) => {
  await signUp(page, { org: `Fx ${uniq()}`, email: `fx-${uniq()}@e2e.test`, sample: true });
  const recorded = await page.evaluate(async () => {
    const me = await (await fetch("/api/auth/me")).json();
    const r = await fetch("/api/payments", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token },
      body: JSON.stringify({ currency: "USD", amount: "5000", payer_name: "BRIGHTWAVE GMBH", reference: "INV-2253", external_ref: "FX-E2E" }) });
    return { ok: r.ok, body: await r.json() };
  });
  expect(recorded.ok, JSON.stringify(recorded.body)).toBeTruthy();
  await page.goto(`/#/payments?deposit=${recorded.body.deposit_id}`);
  await expect(page.getByRole("heading", { name: "Paid in the wrong currency" })).toBeVisible();
  await expect(page.getByText("Recommended: convert only what the invoice needs.")).toBeVisible();
  await page.getByRole("button", { name: "Convert and apply" }).click();
  await expect(page.getByText(/Converted and applied|Conversion booked/).first()).toBeVisible();

  await page.goto("/#/payments?deposit=DEP-1003");
  await expect(page.getByRole("link", { name: "Open email draft" })).toHaveAttribute("href", /^mailto:\?subject=Balance%20due%20on%20INV-2260/);
});

test("CEO view answers the four questions and its numbers lead to the detail", async ({ page }) => {
  await signUp(page, { org: `Ceo ${uniq()}`, email: `ceo-${uniq()}@e2e.test`, sample: true });
  await nav(page, "CEO view");
  await expect(page.getByText(/items? needs? a person/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /Are we safe/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What needs you" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What the agent handled" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Can I trust these numbers?" })).toBeVisible();
  await expect(page.getByText("Not measured.")).toBeVisible();
  await page.screenshot({ path: "test-results/ceo-view.png", fullPage: true });
  await page.getByRole("link", { name: "6", exact: true }).click();
  await expect(page.getByText("DEP-1001").first()).toBeVisible();
  await page.getByRole("button", { name: "Add a wrong-currency payment" }).click();
  await expect(page.getByText(/USD paid against a EUR invoice/)).toBeVisible();
});

test("first-visit guide leads to the agent's decision, and can be hidden", async ({ page }) => {
  await signUp(page, { org: `Guide ${uniq()}`, email: `g-${uniq()}@e2e.test`, sample: true });
  await page.goto("/#/inbox");
  await page.getByRole("link", { name: "Open this payment" }).click();
  await expect(page.getByText("Next:", { exact: true })).toBeVisible();
  await expect(page.getByText("In a real company the agent asks by itself.")).toBeVisible();
  await page.goto("/#/inbox");
  await page.getByRole("button", { name: "Hide this guide" }).click();
  await expect(page.getByRole("heading", { name: "See what it does in three minutes" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Cash by currency" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "See what it does in three minutes" })).toHaveCount(0);
});

test("phone width: bill payments read as cards with nothing to scroll sideways", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await signUp(page, { org: `Cards ${uniq()}`, email: `cards-${uniq()}@e2e.test`, sample: true });
  await page.goto("/#/treasury");
  await page.getByRole("button", { name: "Add a cash squeeze" }).click();
  await page.getByRole("button", { name: "Pay", exact: true }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Propose payment" }).click();
  await page.goto("/#/approvals");
  await expect(page.getByText("Needs a second person")).toBeVisible();
  const wrap = page.locator("table.stack-sm").locator("xpath=ancestor::div[contains(@class,'table-wrap')]");
  expect(await wrap.evaluate((w) => w.scrollWidth - w.clientWidth)).toBeLessThanOrEqual(0);
  await page.screenshot({ path: "test-results/phone-bill-payments.png" });
  await ctx.close();
});

test("dialogs opened from the sidebar are readable and keep focus while typing", async ({ page }) => {
  await signUp(page, { org: `Dialog ${uniq()}`, email: `d-${uniq()}@e2e.test`, sample: false });
  await page.locator(".org-button").click();
  await page.getByRole("menuitem", { name: "New organization…" }).click();
  const dialog = page.getByRole("dialog");
  // Rendered at the top level, not inside the dark sidebar (whose text colour it used to inherit).
  expect(await dialog.evaluate((d) => d.parentElement?.tagName)).toBe("BODY");
  expect(await dialog.getByRole("heading").evaluate((h) => getComputedStyle(h).color)).not.toBe("rgb(255, 255, 255)");
  const name = dialog.getByLabel("Name", { exact: true });
  await name.click();
  await page.keyboard.type("Second org", { delay: 20 });
  await expect(name).toHaveValue("Second org");
  await expect(name).toBeFocused();
});

test("amounts typed with thousands separators are accepted", async ({ page }) => {
  await signUp(page, { org: `Commas ${uniq()}`, email: `c-${uniq()}@e2e.test`, sample: true });
  await nav(page, "Customers");
  await page.getByRole("button", { name: "New invoice" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Customer", { exact: true }).selectOption("CUST-ACME");
  await dialog.getByLabel("Amount", { exact: false }).fill("1,250.50");
  await dialog.getByLabel("Due date", { exact: true }).fill("2026-12-31");
  await dialog.getByLabel("Description", { exact: true }).fill("Thousands separator check");
  await dialog.getByRole("button", { name: "Create invoice" }).click();
  await expect(page.getByText(/Invoice INV-\d+ created/)).toBeVisible();
});

test("payment detail shows the decision path and accounts for every cent", async ({ page }) => {
  await signUp(page, { org: `Path ${uniq()}`, email: `path-${uniq()}@e2e.test`, sample: true });
  await page.goto("/#/payments?deposit=DEP-1001");
  const path = page.getByRole("region", { name: "Decision path" }).or(page.getByLabel("Decision path"));
  await expect(path.getByText("First plan stands")).toBeVisible();
  await expect(path.getByText(/= received amount/)).toBeVisible();
  await page.goto("/#/payments?deposit=DEP-1003");
  await expect(page.getByLabel("Decision path").getByText(/Short by GBP 1,200\.00/)).toBeVisible();
});
