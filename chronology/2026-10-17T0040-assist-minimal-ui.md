# Call center assist: a quieter operator screen

Superseded by the green-chat restoration: the user wanted the original theme and simultaneous transcript/record panels retained. See `2026-10-17-assist-green-cards.md`.

Checkpoint before this change: tag `assist-ui-before-minimal-20261017`, commit `ce8dfd3`. Revert this UI commit and restart only `examples/livelihoods/livestock/call_center_assist/assist/start.sh` to restore it. No changes to the full-call-center bot or its case desk.

The assist at :8776 now opens on a plain, readable transcript. Case record is a separate editable tab. Call setup collapses during the call; practice checks and timings stay collapsed after it. Plain text buttons replace decorative icons. Reading an older transcript line keeps the scroll position when new speech arrives.

Nine overlapping advisory topics are grouped into five fixed classes: herd health, feed and exposure, breathing and standing, digestion and drinking, and birth progress. Only one stacked card is expanded, with Trigger, Ask and Importance. Clearing a card reveals the next; cleared cards can be restored. Clearing is operator review state, not clinical resolution or a change in urgency. A new concern or increased priority reopens the class. Urgent observations remain visible independently.

Each topic has unobtrusive source links to relevant sections of the DAHD Standard Veterinary Treatment Guidelines (2024, official Maharashtra mirror), or NDDB's cyanide guidance. Exact links and page references are in the README and protocol data. These references support observation questions, not approval of keyword triggers, dispatch rules or a diagnosis. The UI explicitly marks veterinary approval as pending. Old treatment readouts, notifiable-disease badges and dispatch-time promises are no longer shown. Legacy advice checks remain in the backend, labeled as unapproved practice checks. Generic mentions of eating no longer trigger the exposure card.

## Verification

- 62 intake, live-call, assist and protocol unit tests passed.
- Chromium layout interactions covered all five classes, clear/restore, source disclosure persistence, keyboard tabs, transcript scroll retention and a 390px mobile viewport without horizontal overflow.
- A real Chromium/WebRTC call with synthetic recorded farmer/operator audio completed: session `20261017-002608-dcd327`, 11/11 expected case fields before the deliberate manual-edit check, eight core practice checks passed, editing passed, clear/restore passed through the live API, and no browser console errors.
- The script did not complete the legacy extra-question, advice-readout and callback checks; this is not a claim of clinical protocol compliance or real-human speech robustness.
- Inspected screenshots of the live transcript, cards, citations, record editor and mobile layout. Adjusted record scrolling after inspecting the completed call.

Screenshots and detailed results stay outside Git on Seagate: `/mnt/seagate/silo/voice-robust/ui-minimal-20261017/` (`before.png`, `after-idle.png`, `layout/`, `live-call/`, `after-record.png`, `after-call.png`). The in-app browser was unavailable; these checks used local Playwright/Chromium. The assist is running at `http://100.82.28.38:8776`; remote HTTP microphone use still needs the browser configuration documented in its README.
