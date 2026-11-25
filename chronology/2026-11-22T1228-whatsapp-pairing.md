# WhatsApp as a source and as a conversation

The owner wants to DM the chatbot, connect their own WhatsApp and Google accounts, and ask a question drawing on both. We started with the smallest observable step, reading a known marker from self-chat. The io experiment already has a guarded WhatsApp Web reader. The bot that accepts a DM uses a separate Meta webhook, whose old tunnel hostname no longer resolves.

We reached the official device pairing screen in a dedicated DGX browser and exposed just the QR through an SSH-forwardable loopback page. Human linking and the actual message read are still open. The [run note](../benchmarks/runs/2026-11-22-whatsapp-onboarding/README.md) records the checks and the two-source follow-up.
