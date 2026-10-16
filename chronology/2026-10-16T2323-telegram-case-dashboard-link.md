# Link submitted Telegram cases to the dashboard

Submission replies now append a direct case-desk URL with the case identifier, so a demonstrator can open the selected case without searching. Replies while awaiting assignment also carry the link. The spoken reply excludes the URL; stored outbound evidence includes the text link.

The default public base is http://100.82.28.38:8766, configurable through LIVESTOCK_DASHBOARD_URL passed by bot.sh. It is separate from the internal LIVESTOCK_URL. The example README documents the assumed Tailscale reachability and port 8766, and distinguishes the optional Fizzy mirror on port 8767, reached through the case desk.

All 31 deterministic tests pass, including submission-link dispatch and keeping the configured URL out of synthesis. HTTP smoke verified the specific case link responds and CASE-7B74AB6DB6 exists in AWAITING_ASSIGNMENT. Restarted only Buffalo after checking the inbox was idle. No case transitions or test Telegram messages were sent. Local commit only.
