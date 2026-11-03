import { expect, test, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// Draft demo video: drives a LOCAL practice company (made-up data, test e-mail) through docs/DEMO_SCRIPT.md, with an
// on-screen caption per narration line, and captures real screen frames. scripts/make_demo_video.py adds the narration.
// Skipped unless DEMO_DIR is set (it holds lines.json and durations.json, and receives the frames and cues).
const DIR = process.env.DEMO_DIR ?? "";
test.skip(!DIR, "set DEMO_DIR to record the demo video");
test.setTimeout(600_000);

test("record the demo video", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const lines: { id: string; text: string }[] = JSON.parse(readFileSync(join(DIR, "lines.json"), "utf8"));
  const seconds: Record<string, number> = JSON.parse(readFileSync(join(DIR, "durations.json"), "utf8"));
  const frames = join(DIR, "frames");
  mkdirSync(frames, { recursive: true });
  // Frames are screenshots stamped with the clock when taken, so the picture never drifts from the narration.
  const stamps: [string, number][] = [];
  let n = 0;
  let recording = true;
  await page.goto("/#/home");
  const recorder = (async () => {
    while (recording) {
      const t = Date.now();
      try {
        const name = `f${String(n++).padStart(6, "0")}.jpg`;
        writeFileSync(join(frames, name), await page.screenshot({ type: "jpeg", quality: 80 }));
        stamps.push([name, t / 1000]);
      } catch { /* mid-navigation: take the next one */ }
      const wait = 120 - (Date.now() - t);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    }
  })();
  const cues: { id: string; start: number }[] = [];

  async function caption(text: string) {
    await page.evaluate((t) => {
      let el = document.getElementById("demo-caption");
      if (!el) {
        el = document.createElement("div");
        el.id = "demo-caption";
        el.style.cssText = "position:fixed;left:50%;bottom:18px;transform:translateX(-50%);max-width:1080px;z-index:99999;" +
          "background:rgba(13,32,56,.92);color:#fff;font:500 17px/1.45 'IBM Plex Sans',system-ui,sans-serif;padding:10px 18px;" +
          "border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.25);text-align:center;pointer-events:none";
        document.body.appendChild(el);
      }
      el.textContent = t;
    }, text);
  }
  // One narration line: show its caption, do the actions, and hold until the line has been spoken.
  async function line(id: string, act: () => Promise<void> = async () => {}) {
    const l = lines.find((x) => x.id === id)!;
    const start = Date.now();
    cues.push({ id, start: start / 1000 });
    await caption(l.text);
    await act();
    await caption(l.text);
    const left = seconds[id] * 1000 + 700 - (Date.now() - start);
    if (left > 0) await page.waitForTimeout(left);
  }
  const runStep = async (title: string) => {
    const row = page.locator(".steps li").filter({ hasText: title });
    await expect(row).toBeVisible({ timeout: 20_000 });  // the steps have loaded
    if ((await row.locator(".n.done").count()) === 0) await row.getByRole("button", { name: "Run", exact: true }).click();
    await expect(row.locator(".n.done")).toHaveCount(1, { timeout: 30_000 });
  };

  await line("intro");
  await line("honest", async () => { await page.mouse.wheel(0, 500); });
  await line("signup", async () => {
    await page.goto("/#/signup");
    await page.getByLabel("Your name", { exact: true }).fill("Demo Owner");
    await page.getByLabel("Organization", { exact: true }).fill("Northbeam Software");
    await page.getByLabel("Work email", { exact: true }).fill(`demo-${randomBytes(3).toString("hex")}@example.test`);
    await page.getByLabel("Password", { exact: true }).fill(`Demo-${randomBytes(9).toString("base64url")}Aa1`);
    await page.getByText("Practice company", { exact: true }).click();
    await page.getByRole("button", { name: "Create organization" }).click();
    await expect(page.getByLabel("Main navigation")).toBeVisible();
  });
  await line("inbox", async () => { await page.goto("/#/inbox"); });
  await line("dup", async () => { await page.goto("/#/payments?deposit=DEP-1005"); });
  await line("ask", async () => {
    await page.getByRole("button", { name: /Ask payer's agent/ }).first().click();
    await expect(page.locator(".drawer").getByText("Verified").first()).toBeVisible({ timeout: 25_000 });
    await page.waitForTimeout(5000);
    await page.locator(".drawer").getByText("Signed payer answer").first().scrollIntoViewIfNeeded();
  });
  await line("reject", async () => {
    await page.goto("/#/payments?deposit=DEP-1004");
    await page.getByRole("button", { name: /Ask payer's agent/ }).first().click();
    await expect(page.locator(".drawer").getByText(/Records check failed/).first()).toBeVisible({ timeout: 25_000 });
  });
  await line("steps", async () => {
    await page.goto("/#/walkthrough");
    for (const t of ["Receive six deposits", "Request the short balance", "Ask payer agents", "Cover the EUR bill"]) await runStep(t);
  });
  await line("approve", async () => {
    await page.goto("/#/approvals");
    await page.getByRole("button", { name: "Approve…" }).click();
    await page.waitForTimeout(2500);
    await page.getByRole("button", { name: "Approve this scope" }).click();
  });
  await line("cannot", async () => { await expect(page.getByText("Practice only")).toBeVisible(); });
  await line("sent", async () => {
    await page.getByRole("button", { name: "Send as practice teammate" }).click();
    await page.goto("/#/walkthrough");
    await runStep("Approve and send the refund");
    await runStep("Bank reports SENT");
  });
  await line("paid", async () => { await runStep("Bank reports PAID"); });
  await line("ledger", async () => { await page.goto("/#/ledger"); });
  await line("ceo", async () => { await page.goto("/#/ceo"); });
  await line("close");
  recording = false;
  await recorder;
  writeFileSync(join(DIR, "frames.json"), JSON.stringify({ stamps, cues }));
});
