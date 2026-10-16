# Remove the livestock compatibility symlink

At the user's request, removed the repository-root `livestock` symlink. The example now uses `examples.livelihoods.livestock.full_call_center` directly for Python imports, tests, bot launch and the Uvicorn application. Fizzy scripts and its generated systemd unit use the canonical example path. Docker Compose explicitly retains the existing `livestock` project name so relocation does not create a different deployment or conflict with the running container.

Updated current READMEs and the narrative. Earlier chronology entries remain historical. Private configuration, runtime state paths and case data are unchanged; the original io bot is untouched. This is an import/service-path change, not an implementation of the proposed conversational design.

Stopped the livestock services after confirming no pending inbox messages, removed the link, and restarted the API, Buffalo bot and Fizzy mirror from their updated paths. Verified the actual running service commands reference the canonical package/directory.

Smoke test without the symlink: all 29 deterministic tests pass (27 discovered tests plus two Fizzy tests), shell syntax passes, and the API health/config/cases/vets endpoints and English landing page respond successfully. The public Fizzy board returns HTTP 200. Buffalo's credentials pass Telegram getMe; no Telegram message was sent and no case was changed by the smoke test. The old top-level `livestock` module is no longer importable. Services remain active.

Committed locally for user review; nothing pushed. The prior freeze tag remains a historical checkpoint rather than being moved.
