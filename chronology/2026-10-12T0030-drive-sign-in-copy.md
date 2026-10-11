# Google Drive: sign in, copy one link, sign out

The user's choice: Google sign-in rather than a service account. When someone pastes a
Drive link, the bot asks them to sign in and copies only that link, with every subfolder,
into their files.

**Design (`tg-bridge/drive.py`):**
- **Sign-in:** OAuth with PKCE and `access_type=online`, so there's no refresh token.
- **The copy:** a recursive Drive v3 copy of the folder. Google's own formats are exported: Sheets
  as xlsx, Docs as md (falling back to txt), Slides as pdf, Drawings as png. Forms and shortcuts
  are skipped and listed. Every item goes into `_drive_manifest.csv` with its path, link, type,
  modified time, owner and a note.
- **Afterwards:** the token is revoked as soon as the copy is done.
- **Scope:** `drive.readonly`, because it's the only scope that can read an existing folder.
  `drive.file` covers only files the app made or picked, and the code-entry device flow allows
  only `drive.file`. Google's consent screen says "all your files", so the bot says first that
  it copies just the link sent.
- **Getting back from Google** needs a URL the phone can reach. The box has none yet:
  - Tailscale has neither HTTPS certs nor Funnel enabled.
  - Cloudflare quick tunnels get a new random host each run, and OAuth redirect URIs must
    be registered in advance.
  - So two modes were built. **Paste-back** (default): a Desktop client redirects to localhost,
    and the user pastes the address of the page that doesn't load. **Automatic**: a Web client,
    `OAUTH_REDIRECT` set to a public https URL such as Tailscale Funnel, and a callback server
    on 127.0.0.1:8791.

**The workspace can hold folders now.**
- `/reset` (`harness.clear`) removes folders.
- `codex_engine` copies them into Codex's job folder.
- The audit record lists every file inside them.

**Tested:**
- Link parsing, including the user's folder link and a Sheets link, the sign-in URL and parsing a
  pasted redirect.
- The copy against a fake Drive tree: subfolder, Sheet, Doc whose md export fails so it falls back
  to txt, pdf, form, shortcut.
- A real question over a nested folder copy (`Swades Funds/2025/…xlsx`): ✅, with Codex and the
  checker both at 5238900. Codex took 50 s and the checker 37 s.
- Live in Telegram: "not set up yet" without a client, and the sign-in prompt and button with a
  placeholder client.
- Not tested: a real Google sign-in, which needs the user's OAuth client.

**A bug found on the way.** Codex sometimes puts the number only on its `ANSWER:` line, which
the bot strips, so the reply read "The Swades Funds file has an Admin category total…"
with no number. When the reply doesn't state the answer, the bot now adds "Answer: <value>".
