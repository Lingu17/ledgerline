# Owner checklist (before submitting)

Only the owner can do these; nothing in this repository saves or submits anything on HackerEarth. The text to paste is in [SUBMISSION_DRAFT](SUBMISSION_DRAFT.md).

In order, before submitting:

1. Server: run `docs/SERVER_STEPS.md` steps 0 to 7 (code live, backups off the server and the two keys in your password manager, owner-only files and sandbox, logs, SSH, email alerts, the recovery drill, the separate sending service) well before the deadline, never during judging.
2. Video: record it, then put its link in the README's top line in place of "3-minute video: coming before 13 Nov" (the comment above that line shows the exact markup).
3. Secrets: on your computer, scan the whole history and check what is tracked. Both must print nothing:
   `git log -p --all | grep -nE "sk-ant-[A-Za-z0-9]|AIza[0-9A-Za-z_-]{30}|-----BEGIN [A-Z ]*PRIVATE KEY|x-api-key: [A-Za-z0-9]{20}"` and
   `git ls-files | grep -iE "(^|/)\.env$|private_keys|agent_key|connections\.key|backup\.key|\.sqlite3$|\.pem$"`
   (or run `gitleaks detect` if you have it).
4. Author email: every commit shows your Gmail address as its author. Leave it, or decide to rewrite history before going public (that needs a force-push; ask first).
5. Make the repository public, then open https://github.com/Lingu17/ledgerline while signed out: the README renders, the links work, the screenshots load.
6. CI: once the repository is public, Actions minutes are free. Trigger a run (Actions → ci → Run workflow, or push a commit) and check it is green, including the PostgreSQL job; until then the README's CI badge shows failing or no status, because runs since 3 Nov were blocked by billing.
7. Licence: there is deliberately no LICENSE file, so the code stays all rights reserved even when the repository is public (the owner's choice). Add one only if you decide to.
8. Security contact (optional, 1 minute): add `LEDGERLINE_SECURITY_CONTACT=mailto:<an address you choose>` (or an https:// page) to `/etc/ledgerline/ledgerline.env` and restart the app, so `/.well-known/security.txt` and the Security page show where to report problems. Until then both say no address is published.
9. Submit on HackerEarth by 13 Nov 23:59 IST with the live link, the repository link and the video link.
10. After submitting: keep the repository public until the results are announced, because judges open the link during judging and a private repository shows them a 404. Making it private afterwards is allowed, but it does not take back what was public: copies people cloned stay with them, and public forks stay public.
