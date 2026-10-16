# Call center assist: retain the green chat interface, simplify only advisories

The user rejected the first minimal redesign: the WhatsApp-like green chat bubbles and the simultaneous transcript on the left and filling care record on the right were intentional. Restored the original base stylesheet, chat styling, dual-panel layout, call controls and after-call layout. Removed the new transcript/record tabs. The advisory stack remains below the care record, now using the original green palette for its header, border and hover states, including dark mode.

Kept the five advisory classes, Trigger / Ask / Importance, discreet source disclosures, one expanded card, and clear/restore interaction from the first pass. Clinical interpretation and speech processing are unchanged by this correction. Inline editing and transcript scroll retention remain available.

Checkpoints: the original interface is `assist-ui-before-minimal-20261017` (`ce8dfd3`); the rejected first pass is `assist-ui-minimal-first-pass-20261017` (`a9cfe38`). This correction is a forward commit, preserving both versions for review. No push.

Browser layout checks passed for simultaneous desktop panels, five advisory classes, clear/restore, citations, keyboard card controls, scroll retention and mobile overflow. Inspected desktop, mobile and dark-mode screenshots. Screenshots and recorded-audio WebRTC test output are outside Git at `/mnt/seagate/silo/voice-robust/ui-green-cards-20261017/`. This is synthetic practice audio, not a human speech benchmark.

The full Chromium/WebRTC recorded-audio call completed: session `20261017-013500-4c2479`, 11/11 expected fields before the intentional edit, successful inline editing, successful live API clear/restore, source links present and no browser console errors. No speech/backend changes were needed.
