# WhatsApp owner test

Can a linked WhatsApp Web session answer a question about a message the owner put in self-chat? The fixture reuses io’s verified-self navigation and visible-message reader. The tester links their own account and sends the synthetic message. The DGX only checks for the marker and reports found, missing or incomplete. The marker result says nothing about full-history coverage.

**Setup.** Use a dedicated OS-owned browser profile directory with mode 700, the local Playwright Python package, a compatible headed Chrome executable and an X display. Start `pair.py --chrome PATH --state PRIVATE_DIR` on the DGX. Forward laptop port 18765 to DGX loopback port 18765 over SSH and open the URL in `PRIVATE_DIR/url`. The URL expires after 30 minutes or after the populated chat list has remained visible for two minutes. The browser profile retains the linked session after the QR server exits. On the phone, use Linked devices to revoke it after testing.

**WhatsApp-only case.** Send `Idli pilot: blue notebook 47` to the owner's self-chat. After pairing exits, run the command below with the private configuration for that owner. The configuration supplies the phone number used to verify self-chat. The reference implementation is in the local io experimental checkout at revision `b400207b`. The test needs its websocket-client dependency. Other chats and the composer are outside this case.

```sh
python3 check_self.py --io-reader "$IO_READER" --private-config "$IO_READER/private/config.json" \
  --chrome "$CHROME" --state "$PRIVATE_DIR"
```

**Cross-source case for later.** In a disposable Google account send the account a test email with the subject “Blue notebook pickup” with a synthetic collection time. Ask “What notebook number did I message myself, and when does the email say to collect it?” Require both fixture values, identify which came from which source, then disconnect one account and verify the missing source is reported. This needs the mailbox binding and both source adapters in one sandbox.

**Preflight on 22 November.** The io reader passed 83 fixture tests. A fresh DGX browser reached the WhatsApp pairing QR. The SSH-forwardable page and QR returned HTTP 200, and an unknown path returned 404. Google Desktop OAuth handled a loopback cancellation without storing a token. The Meta bot phone lookup succeeded, but the old webhook override hostname failed DNS lookup. Live pairing, reading the marker, receiving a bot DM and the cross-source answer require separate evidence.

**First scan.** The phone reported a link error. The fixture had closed the browser as soon as the sidebar appeared. Reopening the same profile on the DGX restored a populated chat list without another scan. The fixture now keeps the browser open during initial sync and shows a refreshing waiting page during transitions. A fresh self-chat marker is the test of current message delivery.

**Live marker read, 22 November.** After the owner sent the fixture, the DGX reopened the same profile. WhatsApp's release-notes dialog covered the self-chat row. The reader now dismisses that specific dialog before using the guarded io navigation. The checker exited 0 on an exact match in the verified self-chat. No chat rows were written to the report. The Google + WhatsApp case and bot delivery are still open.
