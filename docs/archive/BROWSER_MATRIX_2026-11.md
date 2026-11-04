# Browser matrix report, 2026-11-04

- **Branch tested:** `deploy/vercel-render` at `d22f23243d908fc02b28d3a835cf82b157f6d466` ("Account basics: change your name, an owner's reset link, leave, delete a company, delete your account").
- **Setup:** `npm ci`, `npm run build`, backend venv from `backend/requirements-lock.txt`, then the suite against the real API exactly as `frontend/playwright.config.ts` / `.github/workflows/ci.yml` run it (one worker, fresh `e2e/.data`). The extra projects lived in a temporary config outside the repo that imports the repo config; the repo config was not changed.
- **Scope:** test-and-report only. No code fixed, nothing deployed, the live site was not touched, no real keys.

## Headline

1. **Firefox and WebKit could not be run in this environment.** `npx playwright install --with-deps firefox webkit` failed because the environment's network policy denies `cdn.playwright.dev` and `playwright.download.prss.microsoft.com` (HTTP 403 on CONNECT). Both projects then fail at launch with `browserType.launch: Executable doesn't exist at /opt/pw-browsers/webkit-2370/pw_run.sh` (Firefox fails the same way). Ubuntu's `firefox` package is only a snap stub, and Playwright cannot drive stock Firefox or WebKitGTK anyway. **No Safari or Firefox engine result in this report is measured.** The Safari and Firefox items below come from code reading and are labelled *risk (unverified)*. To get real results, allow those two hosts in the environment's network settings, or run the commands in [Re-running](#re-running) on a Mac or in CI.
2. **Chromium is green and stable:** 29/29 passed twice in a row with `--retries=1` and nothing flaky. The 2 skipped tests are skipped by design: `demo-video` needs `DEMO_DIR`, `screenshots` needs `SCREENSHOTS`.
3. **Mobile emulation on the Chromium engine is green:** Pixel 7 got 6/6 and the iPhone 14 descriptor on Chromium got 6/6, twice each. However, three of those six tests open their own `browser.newContext({ viewport })`, which **drops the device settings** (touch, mobile UA, DPR, isMobile), so in those three only the 375 px width was really tested. See [Test-suite gaps](#test-suite-gaps).
4. **Hand walk at 390×844** (iPhone 14 descriptor, Chromium engine): the whole judge path completes, with no horizontal page scroll anywhere. It found **8 visual or usability problems** a phone user would hit, plus **6 Safari-specific risks** in the code. Nothing found breaks the judge path outright.

Note: the repo pins `@playwright/test` 1.64.1, which wants Chromium build 1248. Only build 1243 (Chrome for Testing 153.0.8010.12) was available, so the chromium projects used `executablePath: /opt/pw-browsers/chromium`. CI downloads the matching build and is unaffected.

## Per-browser results

| Project | Engine | Passed | Failed | Flaky | Skipped | Notes |
|---|---|---|---|---|---|---|
| chromium (Desktop Chrome) | Chromium 153 | 29 | 0 | 0 | 2 | Two full runs, identical results |
| firefox (Desktop Firefox) | — | 0 | all (launch) | — | — | Browser not installable: download hosts denied by network policy |
| webkit (Desktop Safari) | — | 0 | all (launch) | — | — | Same as firefox |
| iPhone 14 on webkit | — | 0 | all (launch) | — | — | Same as firefox |
| Pixel 7 on chromium | Chromium 153 | 6 | 0 | 0 | 0 | Judge-path and phone-width tests (grep below) |
| iPhone 14 descriptor on chromium (stand-in) | Chromium 153 | 6 | 0 | 0 | 0 | iPhone viewport, UA, touch and DPR 3; **not** the WebKit engine |

The mobile projects ran the tests matching `/phone width|show me|practice walkthrough|privacy, terms/`:
- `saas.spec.ts:149` phone width: no horizontal overflow
- `saas.spec.ts:276` practice walkthrough with the practice teammate
- `saas.spec.ts:315` three-step path at 375 px
- `saas.spec.ts:350` Show me tour and tamper
- `saas.spec.ts:383` privacy, terms and security pages
- `saas.spec.ts:510` bill payments as cards

**Failures:** only the browser-launch failures listed above. No test assertion failed on any engine that could run. Each launch failure left a `trace.zip` showing an empty trace (the browser never started) and no screenshot.

## Findings by category

### Date and number formatting

- **Numbers:** safe across engines. `money()` and `group()` in `frontend/src/format.ts:1-15` do the string math themselves and never call `toLocaleString`, so grouping and the U+2212 minus sign come out the same in every browser.
- **Dates:**
  - **Risk (unverified):** `format.ts:34` builds `Intl.DateTimeFormat("en-GB", { day, month: "short", hour, minute, timeZone: "UTC" })`. Chromium renders `04 Nov, 17:42 UTC`, as seen in the walk. Safari and Firefox each ship their own CLDR/ICU data, and the separator between date and time can differ (WebKit may render `04 Nov at 17:42`).
    - Impact: cosmetic only. No e2e test asserts a formatted time, so the suite won't catch it either way.
    - Suggested fix: if the exact string matters, build it from `formatToParts`.
  - `format.ts:35` (`day()`, which has no time part) is low risk.
  - Date parsing uses `new Date(iso)` on ISO-8601 strings from the API (`format.ts:39,45,50`, `Treasury.tsx:47,480`, `Approvals.tsx:213`), which all current engines parse.

### CSS layout (375 and 390 px)

- **Page level:** no horizontal page scroll at any of the 30 stops of the walk, at 390 px. The suite's own 375 px checks also pass.
- **Controls off screen inside cards (measured):** on Treasury, the tables are plain `<table>` inside `.table-wrap { overflow-x: auto }` (`styles.css:149`). At 390 px, **Pay**, **Mark paid** (`Treasury.tsx:392-410`, "What to pay first") and **Replay** (`Treasury.tsx:323-338`, "Plan history") sit past the right edge of the card. So does the Credits column of "Wallet position" (`Treasury.tsx:53`). Nothing on screen says the table scrolls sideways, and iOS hides scrollbars. Screenshot: `29-treasury.png`, where the tables are cut off at "Credit" and "Amo…".
  - Suggested fix: add `className="stack-sm"` to these tables, as Bills already does at `Treasury.tsx:202`, or move the action buttons into the first cell.
- **Risk (unverified): `100vh` on iOS Safari.**
  - Where: `.sidebar { height: 100vh }` (`styles.css:58`) and `.modal { max-height: calc(100vh - 48px) }` (`styles.css:210`).
  - Why: iOS Safari's `100vh` is the *large* viewport, about 100 px taller than what is visible while the toolbar shows. The bottom of the mobile menu (`.sidebar-foot` with "Sign out") and the bottom of a tall dialog can end up under Safari's toolbar.
  - Measured: the Approve dialog is 304 px tall and fits.
  - Suggested fix: `height: 100dvh` and `max-height: calc(100dvh - 48px)`, each with the `vh` value kept on the line before as a fallback.

### Clipboard and download

- **Download (works on Chromium):** "Download evidence JSON" on Activity produced `ledgerline-evidence-export.json` under iPhone emulation.
  - **Risk (unverified), Safari and older Firefox:** `api.ts:96-97` calls `a.click()` and then `URL.revokeObjectURL(url)` in the same tick, on an `<a>` that is never attached to the document. WebKit has a history of failing such downloads ("WebKitBlobResource error 1") when the blob URL is revoked before the download starts.
  - Suggested fix: append the anchor to `document.body` before clicking, then `setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000)`.
  - On iPhone the JSON opens in a preview sheet rather than saving silently. That is expected iOS behaviour.
- **Clipboard (works on Chromium):** "Copy message" put the balance-request email on the clipboard. The calls are made directly in click handlers, so Safari's user-gesture rule is met.
  - **Problem (measured):** "Copy message" (`views/Payments.tsx:234`) and "Copy" (`views/Team.tsx:163`) give **no feedback**; the label stays the same after tapping. `Team.tsx:111` does show "Copied".
  - **Risk:** all three use `navigator.clipboard?.writeText(...)` with no `.catch`. If Safari refuses the write (for example after a focus change), or on a plain-http origin where `navigator.clipboard` is undefined, the button silently does nothing.
  - Suggested fix: show "Copied" on success and a toast with the text to copy by hand on failure.

### Fetch and cookies

- **Cookie, measured in the walk:** `ll_session` has `SameSite=Strict`, `Path=/api`, `HttpOnly`, and `Secure=false` (local only; `LEDGERLINE_COOKIE_SECURE=1` sets it on HTTPS). It is set in `backend/ledgerline/api/security.py:83`. Every request is a same-origin `fetch` with `credentials: "same-origin"` (`frontend/src/api.ts:37,89`), and the CSRF token travels in a header. On WebKit a Strict cookie *is* sent on same-origin fetches, so sign-in should hold.
  - **Condition:** this only holds if the browser sees the UI and `/api` on **one origin**. `deploy/vm/Caddyfile:1-3` says requests arrive through Vercel's edge, but this branch contains no `vercel.json`, so I could not check that Vercel rewrites `/api/*` on the same host rather than calling the VM origin cross-site. If the UI ever calls the API on another site, Safari (ITP plus Strict) will drop the session on every request.
  - Confirm the Vercel rewrite in the Vercel dashboard.
- **Google sign-in return:** `oauth_routes.py:83,98` already accounts for the Strict cookie being missing on the cross-site callback by using a separate `SameSite=None` (or Lax) binding cookie. Not testable here: it needs real Google credentials.
- **`crypto.randomUUID()`** (`views/Settings.tsx:234,272`) needs a secure context and Safari 15.4 or later. That is fine on HTTPS, but it throws on a plain-http LAN URL. This is off the judge path.

### Focus and keyboard

- **Risk (unverified), macOS Safari:** by default, Safari's Tab key moves only between form fields, not buttons or links, unless the user has turned on "Press Tab to highlight each item".
  - Where: the focus trap in `components/ui.tsx:168-183` wraps only when `document.activeElement === last`, and `last` is usually a button.
  - Effect: in Safari, Tab from the last *input* of a dialog skips that button and leaves the dialog, into the page behind the scrim. Also, `ui.tsx:168` focuses the first `button` on open, often the × Close.
  - Suggested fix: in the trap, decide inside or outside with `node.contains(e.relatedTarget)` on `focusout` (or check `!node.contains(document.activeElement)` after the Tab), and focus the first form field when there is one.
- **Measured: the off-canvas menu stays in the tab and VoiceOver order.** Below 820 px the closed sidebar is moved off screen with `transform: translateX(-100%)` (`styles.css:278`). `App.tsx:170` gives it neither `inert` nor `aria-hidden`, so its links can still be focused. The walk flagged this on every app page. A keyboard or VoiceOver user on iPhone will move through invisible links.
  - Suggested fix: `<aside inert={!menuOpen && isNarrow}>` (React 18 needs `inert=""`), or `visibility: hidden` when it is closed.
- **Risk (unverified): scroll lock on iOS.** It sets only `document.body.style.overflow = "hidden"` (`ui.tsx:198-200`). iOS Safari before 16 ignores this, so the page behind an open drawer still scrolls when you drag.
  - Suggested fix: also set `position: fixed` and `top: -scrollY` on the body while locked, and restore both afterwards.

### Judge-path breakers

No breakers on the Chromium engine: every judge step finished at 390×844 with only touch input (`tap()`). The steps covered:

1. Sign up a Practice company.
2. Payments → DEP-1005 → Ask payer's agent, ending at Verified.
3. Replay this decision, which returned "Same plan".
4. Why this plan, which showed a cited explanation.
5. The four practice steps.
6. Approve this scope.
7. Send as practice teammate.
8. Bank SENT and Bank PAID, with all 8 steps done.
9. Show me, stops 1 to 7.
10. Try to tamper, which reported "Caught at event N", then Restore.
11. Treasury Replay.
12. The Privacy, Terms and Security pages.

The only console error was an expected 401 from `/api/auth/me` before sign-up. Safari and Firefox could not be checked, see the Headline.

## Hand walk: webkit at 390×844 — run as the iPhone 14 descriptor on Chromium

The WebKit binary was unavailable, so the walk used Playwright's "iPhone 14" device (Safari UA, touch, DPR 3, `isMobile`) with the viewport forced to 390×844, on the Chromium engine. Screenshots and per-stop measurements were saved outside the repo, in the session scratchpad (`walk-shots/NN-*.png` and `notes.json`).

Problems an iPhone or Safari user would hit, most visible first:

| # | Problem | Where | Measured or risk | Suggested fix |
|---|---|---|---|---|
| 1 | **Every text field and select uses 14 px type, so iOS Safari zooms the page on focus.** Typing on the sign-up page zooms in, and the user has to pinch back out. The same happens on the Payments filters and the Activity search. | `styles.css:36`: body is `font: 14px`; `styles.css:39`: inputs inherit it; `styles.css:166` | Measured: `INPUT@14px` on signup, payments and activity | `@media (max-width: 820px) { input, select, textarea { font-size: 16px; } }`. Do not use `maximum-scale=1`, which blocks zoom for low-vision users. |
| 2 | **Show me panel covers the bottom 145–200 px of the screen,** including the bottom of the DEP-1005 drawer: the Decision text, the allocation line and the "Replay this decision" button behind it. The drawer's bottom padding is only 40 px, so the last content can never be scrolled clear of the panel. | `.showme` at `styles.css:193`; `.drawer-body` padding at `styles.css:205` | Measured: panel top at 631 px of 844 on stop 3 (`21-tour_3_A_suspected_duplicate.png`) | While the tour is open, add bottom padding equal to the panel height to `.drawer-body` and `.content`. Or, at ≤640 px, make the panel a collapsible bar. |
| 3 | **Toasts sit on top of the Show me panel.** Both are fixed at the bottom right (toasts `z-index: 40` over the panel's 30), and the tour's own actions raise toasts. For 4.5 s the tour text and its Next and Back buttons are hidden, so a judge tapping Next can hit a toast instead. | `styles.css:265` vs `styles.css:193`; toast lifetime `ui.tsx:61` | Measured: `19-tour_1.png` shows four toasts covering the panel | While the tour is open, move `.toasts` to the top on narrow screens (`top: 12px; bottom: auto`), or above the panel with `bottom: calc(panel height + 24px)`. |
| 4 | **Treasury action buttons are off screen.** Pay, Mark paid, Replay and the Credits column are only reachable by swiping inside a table, with no hint that it scrolls. | `Treasury.tsx:53, 323-338, 392-410`; `styles.css:149` | Measured (`29-treasury.png`) | Add `stack-sm` to these tables, as Bills already does at `Treasury.tsx:202`. Or add a fade at the right edge of the scroll area. |
| 5 | **Tap targets are small.** Buttons are 32 px high (`.btn`) and 26 px (`.btn.small`, used for Run, Replay this decision, Next and Back in the tour). That is below Apple's 44 pt guideline, and adjacent Back and Next buttons are easy to mis-tap. | `styles.css:109, 119` | Measured: 6–17 controls under 44 px on every app page | `@media (pointer: coarse) { .btn { min-height: 44px } .btn.small { min-height: 36px } }` |
| 6 | **The hidden mobile menu can still be focused** by VoiceOver and the keyboard. | `App.tsx:170`, `styles.css:278` | Measured | Set `inert` while closed (see Focus and keyboard). |
| 7 | **"Copy message" gives no confirmation.** | `Payments.tsx:234`, `Team.tsx:163` | Measured | Show "Copied", as `Team.tsx:111` does, and a fallback on failure. |
| 8 | **The mobile menu footer (Sign out) may sit under Safari's toolbar.** | `styles.css:58` (`100vh`) | Risk | `100dvh` |
| 9 | **Evidence download may fail on Safari.** | `api.ts:96-97` | Risk | Attach the anchor and delay the revoke. |
| 10 | **Dialog focus can escape on macOS Safari.** | `ui.tsx:174-183` | Risk | Use a `focusout`-based trap. |
| 11 | **The page behind the drawer scrolls on iOS before 16.** | `ui.tsx:198-200` | Risk | Body `position: fixed` lock. |
| 12 | **Date-time separator may differ** (`, ` vs ` at `). | `format.ts:34` | Risk, cosmetic | Use `formatToParts`. |
| 13 | **Hover colours stick after a tap on iOS.** `.btn:hover`, `tr.clickable:hover` and the nav hover stay painted until the next tap, which looks like a selected state. | `styles.css:71, 112, 155` | Risk, cosmetic | Wrap them in `@media (hover: hover)`. |

What worked well at 390 px:
- No page-level sideways scroll.
- The drawer is full width (390 px).
- The Approve dialog fits within Safari's visible area (top 270, bottom 574 of a visible 664).
- Bills and payments stack as cards.
- The Privacy, Terms and Security pages have no small controls and no overflow.

## Test-suite gaps

- `saas.spec.ts:150, 316, 351` (and `journey.spec.ts:213`) create contexts with only `{ viewport: { width: 375, height: 812 } }`. In a device project this throws away touch, mobile UA, DPR and `isMobile`, so these tests check *width* and not *phone*. Spreading the project's `use`, or using `test.use({ ...devices[...] })`, would make the iPhone and Pixel projects meaningful.
- The suite has no check for input font sizes, tap-target sizes, the tour panel covering content, or overlap between toasts and the tour. The issues in rows 1–5 of the walk table would not be caught.
- CI (`ci.yml`) installs and runs Chromium only. Adding `firefox` and `webkit` projects needs about `npx playwright install --with-deps firefox webkit` (roughly 150 MB) in the e2e job.

## Re-running

From `frontend/`, with network access to the Playwright CDN:

```bash
npx playwright install --with-deps firefox webkit
```

Then use a config outside the repo that imports `playwright.config.ts`, sets `channel: undefined`, and defines these projects:
- `chromium` (Desktop Chrome)
- `firefox` (Desktop Firefox)
- `webkit` (Desktop Safari)
- `iPhone 14` with `grep` for the mobile tests
- `Pixel 7` with `grep` for the mobile tests

Run it with `npx playwright test -c <that config> --retries=1`.
