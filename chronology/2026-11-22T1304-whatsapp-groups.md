# Read the group once, ask the local store

The owner proposed using the WhatsApp UI to download individual groups and poll for updates. We tested that separation with two one-off group snapshots. The second reproduced all 2,701 captured texts. An unanchored library call had silently returned an empty Jam Buns history, which made the independent cache count important.

The core could retrieve the newest link and sender directly. Conversationally, an abbreviated group title often became an exact filter and one WhatsApp question went to Gmail. Resolve the group and verify coverage before interpreting an empty answer. The owner can now compare a remembered link against the frozen sandbox and their phone. [Run, cases, limits and manual test](../benchmarks/runs/2026-11-22-whatsapp-groups/README.md)
