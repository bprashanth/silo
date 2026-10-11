# WhatsApp: a dead end

The first goal was a WhatsApp number that four teammates could message, with
replies from Muse Glimmer 30B on OpenRouter.

`wa-bridge/bridge.py` is a webhook server behind a Cloudflare quick tunnel. It
verified the webhook, received messages and replied through the Cloud API. One
round trip worked from the test number ("Testing" → "Test received.").

Delivery to real phones then failed in sequence:

- 141006: no payment method on the business account. Fixed by adding one.
- 141010: business verification incomplete.
- 131031: "Business account locked". Re-registering the number (PIN 246810)
  and the account becoming AVAILABLE did not clear it.

A headless Facebook login hit reCAPTCHA and was not automated; the account IDs
were supplied by hand. The WhatsApp path was abandoned for Telegram. The bridge
is stopped. The WABA webhook override still points at a dead trycloudflare URL.
