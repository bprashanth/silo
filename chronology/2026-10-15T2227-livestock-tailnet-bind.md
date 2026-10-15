# Livestock POC network bind

At the user’s request, start.sh now defaults HOST to 0.0.0.0 (still overridable). Restarted only the isolated benchmark and verified HTTP health via http://100.82.28.38:8765/api/health. No Tailscale Serve configuration was applied; the pending enablement command was cancelled. Browser microphone capture on plain remote HTTP remains subject to browser secure-context restrictions; localhost via SSH forwarding or HTTPS supports microphone access.
