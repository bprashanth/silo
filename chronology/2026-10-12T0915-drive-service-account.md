# Drive via a service account

**Why:** the Google sign-in flow (2026-10-12T0030) needs every user's Gmail on the OAuth app's
test-user list while it's in Testing. Getting out of Testing means Google's verification,
which for `drive.readonly` includes a paid security assessment. Users would also see two
warnings, "unverified app" and "see and download all your Google Drive files", and sign in
again for each refresh. With a service account, users share one folder with the account's
email as a Viewer and paste the link. There's no per-user setup on our side, and the
account sees only what's shared with it.

**What changed:**
- `drive.py`:
  - `sa()` / `sa_email()` / `sa_token()`: reads `$SILO_CONFIG/drive_sa.json` and signs an RS256 JWT
    with the `openssl` CLI (no new Python dependency), swapping it for a one-hour
    `drive.readonly` token.
  - `NoAccess` is raised when the link itself is 403/404.
- `tg_bridge.py`:
  - When the key exists, a pasted link is copied straight away.
  - `NoAccess` gets a reply naming the email to share with.
  - The sign-in flow stays as the fallback (`drive_signed_in`), and both paths share `drive_copy`.
  - The audit `drive` record now says `via`.
- `docs/deployment.md`: setup for both, with the service account recommended.

**Tested live (Telegram, the user's account):**
- The user's folder "Cell Ag", shared with `drive-silo@bitrot-in.iam.gserviceaccount.com`,
  copied as 13 files in 5 folders, 1.7 MB, in 22 s: 11 `.docx`, 1 PDF, and 1 Google Doc
  exported as `.md`.
- A made-up folder id got the "share it with …" reply.

**A question over it:** "how many Tufts protocol documents, and which week has the most"
came back ⚠️. Codex answered `Wk4` and the checker answered `10`, and both are right. The
question has two answers and each side put a different one on its `ANSWER:` line. That's a
comparison limit for multi-part questions, not a Drive problem.

**Open:**
- Anyone on the allowlist with a shared link can copy it. The fix would be to tie Telegram
  users to Gmail addresses and check the owner.
- The checker's sandbox has no `.docx` reader. Word files are zipped XML, so it can still
  get at them with `zipfile`, but converting `.docx` to `.md` while copying would be kinder
  to both harnesses.
