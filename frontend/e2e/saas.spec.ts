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
  if (opts.sample) await page.getByText("Sample data", { exact: true }).click();
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("navigation", { name: "Main navigation" }).or(page.getByLabel("Main navigation"))).toBeVisible();
}

async function nav(page: Page, label: string) {
  await page.getByLabel("Main navigation").getByRole("link", { name: label, exact: false }).first().click();
}

test("sign up with sample data, sign out, sign back in", async ({ page }) => {
  const email = `owner-${uniq()}@e2e.test`;
  await signUp(page, { org: `Sample ${uniq()}`, email, sample: true });
  await expect(page.getByLabel("Main navigation").getByText("Walkthrough")).toBeVisible();
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

test("Google and Apple buttons are shown, and honest when the server has no OAuth credentials", async ({ page }) => {
  await page.goto("/#/signin");
  const google = page.getByRole("button", { name: "Continue with Google" });
  const apple = page.getByRole("button", { name: "Continue with Apple" });
  await expect(google).toBeDisabled();
  await expect(apple).toBeDisabled();
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
  await expect(card.getByText("Not set up on this server")).toHaveCount(2);
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
  await expect(page.getByLabel("Main navigation").getByText("Walkthrough")).toHaveCount(0);
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
