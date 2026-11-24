// Read-only WhatsApp sync sidecar built on whatsmeow.
// Zero write/send methods are imported or called: no SendMessage, no MarkRead,
// no presence updates. Captures HistorySync and live messages for the configured
// rolling window into a private snapshot JSON inside the state directory.
package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"html"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
	qrcode "github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
)

type CapturedMessage struct {
	ID          string   `json:"id"`
	StanzaID    string   `json:"stanza_id"`
	ChatID      string   `json:"chat_id"`
	ChatName    string   `json:"chat_name"`
	IsGroup     bool     `json:"is_group"`
	Timestamp   int64    `json:"t"`
	SenderID    string   `json:"sender_id"`
	Sender      string   `json:"sender"`
	IsFromMe    bool     `json:"is_from_me"`
	SourceType  string   `json:"source_type"`
	Body        string   `json:"body"`
	LinkPreview string   `json:"preview,omitempty"`
	Filename    string   `json:"filename,omitempty"`
	ParentID    string   `json:"parent,omitempty"`
	Links       []string `json:"links,omitempty"`
}

type CapturedChat struct {
	ID         string            `json:"id"`
	Name       string            `json:"name"`
	IsGroup    bool              `json:"is_group"`
	ActiveAt   int64             `json:"active_at"`
	EarliestAt int64             `json:"earliest_at"`
	LatestAt   int64             `json:"latest_at"`
	Rows       []CapturedMessage `json:"rows"`
}

type Snapshot struct {
	Provider  string         `json:"provider"`
	Since     string         `json:"since"`
	AsOf      string         `json:"as_of"`
	WindowDay int            `json:"window_days"`
	Groups    []CapturedChat `json:"groups"`
	DMs       []CapturedChat `json:"dms"`
}

type State struct {
	mu           sync.Mutex
	client       *whatsmeow.Client
	stateDir     string
	windowDays   int
	cutoffUnix   int64
	status       string
	qrPNGDataURI string
	qrUpdatedAt  time.Time
	pairCode     string
	pairErr      string
	pairedJID    string
	historyBlobs int
	chatNames    map[string]string
	contacts     map[string]string
	messages     map[string]CapturedMessage // key: chat_id|stanza_id
	dirty        bool
}

var (
	urlRe     = regexp.MustCompile(`(?i)https?://[^\s<>"\x{200b}]+`)
	domainRe  = regexp.MustCompile(`(?i)\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:org|com|in|net|io|co|edu|gov|ai|cc|me|app|dev)(?:/[^\s<>"\x{200b}]*)?`)
	digitsRe  = regexp.MustCompile(`\D+`)
	mentionRe = regexp.MustCompile(`@([0-9]{10,18})\b`)
)

func isAllDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func extractLinks(text string) []string {
	seen := map[string]bool{}
	var out []string
	for _, u := range urlRe.FindAllString(text, -1) {
		u = strings.TrimRight(u, ".,;!?)")
		if !seen[u] {
			seen[u] = true
			out = append(out, u)
		}
	}
	for _, d := range domainRe.FindAllString(text, -1) {
		d = strings.TrimRight(d, ".,;!?)")
		dup := false
		for k := range seen {
			if strings.Contains(strings.ToLower(k), strings.ToLower(d)) {
				dup = true
				break
			}
		}
		if !dup && !seen[d] {
			seen[d] = true
			out = append(out, d)
		}
	}
	return out
}

func unpackMessage(m *waE2E.Message) (body, sourceType, preview, filename, quotedStanza string) {
	if m == nil {
		return
	}
	// Unwrap ephemeral / view-once / document-with-caption wrappers.
	for i := 0; i < 4 && m != nil; i++ {
		switch {
		case m.GetEphemeralMessage().GetMessage() != nil:
			m = m.GetEphemeralMessage().GetMessage()
		case m.GetViewOnceMessage().GetMessage() != nil:
			m = m.GetViewOnceMessage().GetMessage()
		case m.GetViewOnceMessageV2().GetMessage() != nil:
			m = m.GetViewOnceMessageV2().GetMessage()
		case m.GetDocumentWithCaptionMessage().GetMessage() != nil:
			m = m.GetDocumentWithCaptionMessage().GetMessage()
		case m.GetEditedMessage().GetMessage() != nil:
			m = m.GetEditedMessage().GetMessage()
		default:
			i = 10
		}
	}
	if m == nil {
		return
	}
	if s := strings.TrimSpace(m.GetConversation()); s != "" {
		return s, "text", "", "", ""
	}
	if ext := m.GetExtendedTextMessage(); ext != nil {
		body = strings.TrimSpace(ext.GetText())
		sourceType = "text"
		var pv []string
		if t := strings.TrimSpace(ext.GetTitle()); t != "" {
			pv = append(pv, t)
		}
		if d := strings.TrimSpace(ext.GetDescription()); d != "" {
			pv = append(pv, d)
		}
		if u := strings.TrimSpace(ext.GetMatchedText()); u != "" && !strings.Contains(body, u) {
			pv = append(pv, u)
		}
		preview = strings.Join(pv, " ")
		if len(preview) > 2000 {
			preview = preview[:2000]
		}
		if ci := ext.GetContextInfo(); ci != nil {
			quotedStanza = ci.GetStanzaID()
		}
		return
	}
	if img := m.GetImageMessage(); img != nil {
		body = strings.TrimSpace(img.GetCaption())
		sourceType = "image_caption"
		if ci := img.GetContextInfo(); ci != nil {
			quotedStanza = ci.GetStanzaID()
		}
		return
	}
	if vid := m.GetVideoMessage(); vid != nil {
		body = strings.TrimSpace(vid.GetCaption())
		sourceType = "video_caption"
		if ci := vid.GetContextInfo(); ci != nil {
			quotedStanza = ci.GetStanzaID()
		}
		return
	}
	if doc := m.GetDocumentMessage(); doc != nil {
		filename = strings.TrimSpace(doc.GetFileName())
		body = strings.TrimSpace(doc.GetCaption())
		if body == "" && filename != "" {
			body = "[Document: " + filename + "]"
		}
		sourceType = "document"
		if ci := doc.GetContextInfo(); ci != nil {
			quotedStanza = ci.GetStanzaID()
		}
		return
	}
	return
}

func (s *State) canonicalJID(ctx context.Context, jid types.JID) types.JID {
	j := jid.ToNonAD()
	if j.Server == types.HiddenUserServer && s.client != nil && s.client.Store != nil && s.client.Store.LIDs != nil {
		if pn, err := s.client.Store.LIDs.GetPNForLID(ctx, j); err == nil && !pn.IsEmpty() {
			return pn.ToNonAD()
		}
	}
	return j
}

func (s *State) lookupContactName(ctx context.Context, jid types.JID) string {
	if jid.IsEmpty() || s.client == nil || s.client.Store == nil || s.client.Store.Contacts == nil {
		return ""
	}
	if info, err := s.client.Store.Contacts.GetContact(ctx, jid.ToNonAD()); err == nil && info.Found {
		for _, cand := range []string{info.FullName, info.FirstName, info.PushName, info.BusinessName} {
			if c := strings.TrimSpace(cand); c != "" && !isAllDigits(c) {
				return c
			}
		}
	}
	return ""
}

func (s *State) resolveSender(ctx context.Context, jid types.JID, pushName string, fromMe bool) (string, string) {
	if fromMe {
		return "me", "Me"
	}
	raw := jid.ToNonAD()
	canon := s.canonicalJID(ctx, raw)
	id := canon.String()
	// Check in-memory cache (canonical first, then raw LID)
	for _, k := range []string{id, raw.String()} {
		if name := s.contacts[k]; name != "" && !isAllDigits(name) {
			return id, name
		}
	}
	// Query whatsmeow contact store for canonical PN JID first, then raw LID JID
	for _, candJID := range []types.JID{canon, raw} {
		if name := s.lookupContactName(ctx, candJID); name != "" {
			s.contacts[id] = name
			s.contacts[raw.String()] = name
			return id, name
		}
	}
	if p := strings.TrimSpace(pushName); p != "" && !isAllDigits(p) {
		s.contacts[id] = p
		s.contacts[raw.String()] = p
		return id, p
	}
	if canon.User != "" {
		return id, canon.User
	}
	if raw.User != "" {
		return id, raw.User
	}
	return id, "Unknown"
}

func (s *State) resolveMentionDigits(ctx context.Context, digits string) string {
	// Try as LID first, then as phone JID
	for _, srv := range []string{types.HiddenUserServer, types.DefaultUserServer} {
		j := types.NewJID(digits, srv)
		_, name := s.resolveSender(ctx, j, "", false)
		if name != "" && name != "Unknown" && !isAllDigits(name) {
			return name
		}
	}
	return ""
}

func (s *State) resolveMentions(ctx context.Context, body string) string {
	if !strings.Contains(body, "@") {
		return body
	}
	return mentionRe.ReplaceAllStringFunc(body, func(match string) string {
		digits := match[1:]
		if name := s.resolveMentionDigits(ctx, digits); name != "" {
			return "@" + name
		}
		return match
	})
}

func (s *State) backfillNames(ctx context.Context) int {
	updated := 0
	for key, msg := range s.messages {
		changed := false
		if !msg.IsFromMe && (isAllDigits(msg.Sender) || strings.HasSuffix(msg.SenderID, "@lid")) {
			if j, err := types.ParseJID(msg.SenderID); err == nil {
				newID, newName := s.resolveSender(ctx, j, "", false)
				if newID != msg.SenderID || newName != msg.Sender {
					msg.SenderID = newID
					msg.Sender = newName
					changed = true
				}
			}
		}
		if !msg.IsGroup && (isAllDigits(msg.ChatName) || strings.Contains(msg.ChatName, "@")) {
			if cj, err := types.ParseJID(msg.ChatID); err == nil {
				_, cname := s.resolveSender(ctx, cj, "", false)
				if cname != "" && cname != "Unknown" && !isAllDigits(cname) && cname != msg.ChatName {
					msg.ChatName = cname
					s.chatNames[msg.ChatID] = cname
					changed = true
				}
			}
		}
		newBody := s.resolveMentions(ctx, msg.Body)
		if newBody != msg.Body {
			msg.Body = newBody
			changed = true
		}
		if changed {
			s.messages[key] = msg
			updated++
		}
	}
	if updated > 0 {
		s.dirty = true
	}
	return updated
}

func (s *State) resolveChatName(ctx context.Context, chatJID types.JID, fallback string) string {
	id := chatJID.ToNonAD().String()
	if strings.TrimSpace(fallback) != "" {
		s.chatNames[id] = strings.TrimSpace(fallback)
		return s.chatNames[id]
	}
	if name := s.chatNames[id]; name != "" {
		return name
	}
	if chatJID.Server == types.GroupServer && s.client != nil && s.client.IsConnected() {
		if gi, err := s.client.GetGroupInfo(ctx, chatJID); err == nil && gi != nil && strings.TrimSpace(gi.Name) != "" {
			s.chatNames[id] = strings.TrimSpace(gi.Name)
			return s.chatNames[id]
		}
	}
	if chatJID.Server != types.GroupServer {
		_, nm := s.resolveSender(ctx, chatJID, "", false)
		if nm != "" && nm != "Unknown" {
			s.chatNames[id] = nm
			return nm
		}
	}
	return id
}

func (s *State) recordMessage(ctx context.Context, chatJID types.JID, chatNameHint string, stanzaID string, ts int64, senderJID types.JID, pushName string, fromMe bool, raw *waE2E.Message) {
	if ts < s.cutoffUnix || stanzaID == "" || chatJID.IsEmpty() {
		return
	}
	// Skip status broadcasts and newsletters.
	if chatJID.Server == types.BroadcastServer || chatJID.Server == types.NewsletterServer {
		return
	}
	body, srcType, preview, filename, quotedStanza := unpackMessage(raw)
	if body == "" && filename == "" {
		return
	}
	chatID := chatJID.ToNonAD().String()
	isGroup := chatJID.Server == types.GroupServer
	chatName := s.resolveChatName(ctx, chatJID, chatNameHint)
	senderID, sender := s.resolveSender(ctx, senderJID, pushName, fromMe)
	body = s.resolveMentions(ctx, body)
	key := chatID + "|" + stanzaID
	parentID := ""
	if quotedStanza != "" {
		parentID = chatID + "|" + quotedStanza
	}
	s.messages[key] = CapturedMessage{
		ID:          key,
		StanzaID:    stanzaID,
		ChatID:      chatID,
		ChatName:    chatName,
		IsGroup:     isGroup,
		Timestamp:   ts,
		SenderID:    senderID,
		Sender:      sender,
		IsFromMe:    fromMe,
		SourceType:  srcType,
		Body:        body,
		LinkPreview: preview,
		Filename:    filename,
		ParentID:    parentID,
		Links:       extractLinks(body + " " + preview),
	}
	s.dirty = true
}

func (s *State) flushSnapshot() error {
	s.mu.Lock()
	if !s.dirty {
		s.mu.Unlock()
		return nil
	}
	byChat := map[string]*CapturedChat{}
	for _, msg := range s.messages {
		c, ok := byChat[msg.ChatID]
		if !ok {
			name := s.chatNames[msg.ChatID]
			if name == "" {
				name = msg.ChatName
			}
			c = &CapturedChat{
				ID:         msg.ChatID,
				Name:       name,
				IsGroup:    msg.IsGroup,
				EarliestAt: msg.Timestamp,
				LatestAt:   msg.Timestamp,
				ActiveAt:   msg.Timestamp,
			}
			byChat[msg.ChatID] = c
		}
		if msg.Timestamp < c.EarliestAt {
			c.EarliestAt = msg.Timestamp
		}
		if msg.Timestamp > c.LatestAt {
			c.LatestAt = msg.Timestamp
			c.ActiveAt = msg.Timestamp
		}
		c.Rows = append(c.Rows, msg)
	}
	var groups, dms []CapturedChat
	for _, c := range byChat {
		sort.Slice(c.Rows, func(i, j int) bool {
			if c.Rows[i].Timestamp != c.Rows[j].Timestamp {
				return c.Rows[i].Timestamp < c.Rows[j].Timestamp
			}
			return c.Rows[i].StanzaID < c.Rows[j].StanzaID
		})
		if c.IsGroup {
			groups = append(groups, *c)
		} else {
			dms = append(dms, *c)
		}
	}
	sort.Slice(groups, func(i, j int) bool { return groups[i].ActiveAt > groups[j].ActiveAt })
	sort.Slice(dms, func(i, j int) bool { return dms[i].ActiveAt > dms[j].ActiveAt })
	snap := Snapshot{
		Provider:  "whatsapp",
		Since:     time.Unix(s.cutoffUnix, 0).UTC().Format(time.RFC3339),
		AsOf:      time.Now().UTC().Format(time.RFC3339),
		WindowDay: s.windowDays,
		Groups:    groups,
		DMs:       dms,
	}
	s.dirty = false
	s.mu.Unlock()

	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		return err
	}
	tmp := filepath.Join(s.stateDir, "snapshot.json.tmp")
	dst := filepath.Join(s.stateDir, "snapshot.json")
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, dst)
}

func (s *State) stats() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	groupSet := map[string]bool{}
	dmSet := map[string]bool{}
	var earliest, latest int64
	for _, m := range s.messages {
		if m.IsGroup {
			groupSet[m.ChatID] = true
		} else {
			dmSet[m.ChatID] = true
		}
		if earliest == 0 || m.Timestamp < earliest {
			earliest = m.Timestamp
		}
		if m.Timestamp > latest {
			latest = m.Timestamp
		}
	}
	out := map[string]any{
		"status":        s.status,
		"paired":        s.pairedJID != "",
		"qr_png":        s.qrPNGDataURI,
		"pair_code":     s.pairCode,
		"pair_error":    s.pairErr,
		"history_blobs": s.historyBlobs,
		"groups":        len(groupSet),
		"dms":           len(dmSet),
		"messages":      len(s.messages),
		"window_days":   s.windowDays,
	}
	if earliest > 0 {
		out["earliest"] = time.Unix(earliest, 0).Format("2006-01-02 15:04")
		out["latest"] = time.Unix(latest, 0).Format("2006-01-02 15:04")
	}
	return out
}

func randomToken(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

func main() {
	stateDir := flag.String("state", "/state", "private state directory (mode 0700)")
	listenAddr := flag.String("listen", "0.0.0.0:18766", "HTTP listen address")
	publicBase := flag.String("public-base", "http://127.0.0.1:18766", "base URL printed to stderr")
	days := flag.Int("days", 14, "rolling history window in days")
	flag.Parse()

	if err := os.MkdirAll(*stateDir, 0o700); err != nil {
		log.Fatalf("mkdir state: %v", err)
	}
	token := ""
	if existingURL, err := os.ReadFile(filepath.Join(*stateDir, "url")); err == nil {
		if idx := strings.LastIndex(strings.TrimSpace(string(existingURL)), "/pair/"); idx >= 0 {
			token = strings.TrimSpace(string(existingURL))[idx+len("/pair/"):]
		}
	}
	if token == "" {
		token = randomToken(16)
	}
	urlStr := strings.TrimRight(*publicBase, "/") + "/pair/" + token
	_ = os.WriteFile(filepath.Join(*stateDir, "url"), []byte(urlStr+"\n"), 0o600)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	dbPath := filepath.Join(*stateDir, "whatsmeow.db")
	dbLog := waLog.Stdout("DB", "WARN", true)
	container, err := sqlstore.New(ctx, "sqlite3", "file:"+dbPath+"?_foreign_keys=on&_busy_timeout=5000", dbLog)
	if err != nil {
		log.Fatalf("sqlstore: %v", err)
	}
	deviceStore, err := container.GetFirstDevice(ctx)
	if err != nil {
		log.Fatalf("device: %v", err)
	}

	clientLog := waLog.Stdout("WA", "WARN", true)
	client := whatsmeow.NewClient(deviceStore, clientLog)
	client.EnableAutoReconnect = true

	st := &State{
		client:     client,
		stateDir:   *stateDir,
		windowDays: *days,
		cutoffUnix: time.Now().Add(-time.Duration(*days) * 24 * time.Hour).Unix(),
		status:     "starting",
		chatNames:  map[string]string{},
		contacts:   map[string]string{},
		messages:   map[string]CapturedMessage{},
	}

	// Preload any existing snapshot so restarts keep already-captured messages,
	// and backfill any previously unresolved @lid senders / @mentions from whatsmeow.db.
	if existing, err := os.ReadFile(filepath.Join(*stateDir, "snapshot.json")); err == nil {
		var prev Snapshot
		if json.Unmarshal(existing, &prev) == nil {
			for _, g := range append(prev.Groups, prev.DMs...) {
				st.chatNames[g.ID] = g.Name
				for _, m := range g.Rows {
					if m.Timestamp >= st.cutoffUnix {
						st.messages[m.ID] = m
					}
				}
			}
			if n := st.backfillNames(ctx); n > 0 {
				log.Printf("backfilled %d cached messages with resolved contact names", n)
				_ = st.flushSnapshot()
			}
		}
	}

	client.AddEventHandler(func(evt any) {
		switch v := evt.(type) {
		case *events.Connected:
			st.mu.Lock()
			st.status = "connected"
			if client.Store.ID != nil {
				st.pairedJID = client.Store.ID.User
				st.qrPNGDataURI = ""
				st.pairCode = ""
			}
			st.mu.Unlock()
			log.Printf("connected (read-only), waiting for history sync...")
		case *events.PairSuccess:
			st.mu.Lock()
			st.status = "paired_syncing"
			st.pairedJID = v.ID.User
			st.qrPNGDataURI = ""
			st.pairCode = ""
			st.mu.Unlock()
			log.Printf("paired successfully; waiting for history sync blobs...")
		case *events.HistorySync:
			data := v.Data
			if data == nil {
				return
			}
			st.mu.Lock()
			st.status = "syncing_history"
			st.historyBlobs++
			for _, pn := range data.GetPushnames() {
				if jid, err := types.ParseJID(pn.GetID()); err == nil && strings.TrimSpace(pn.GetPushname()) != "" {
					st.contacts[jid.ToNonAD().String()] = strings.TrimSpace(pn.GetPushname())
				}
			}
			added := 0
			for _, conv := range data.GetConversations() {
				chatJID, err := types.ParseJID(conv.GetID())
				if err != nil {
					continue
				}
				chatName := strings.TrimSpace(conv.GetName())
				if chatName == "" {
					chatName = strings.TrimSpace(conv.GetDisplayName())
				}
				if chatName != "" {
					st.chatNames[chatJID.ToNonAD().String()] = chatName
				}
				for _, hm := range conv.GetMessages() {
					wm := hm.GetMessage()
					if wm == nil || wm.GetKey() == nil {
						continue
					}
					key := wm.GetKey()
					ts := int64(wm.GetMessageTimestamp())
					fromMe := key.GetFromMe()
					senderJID := chatJID
					if p := key.GetParticipant(); p != "" {
						if pj, err := types.ParseJID(p); err == nil {
							senderJID = pj
						}
					} else if p := wm.GetParticipant(); p != "" {
						if pj, err := types.ParseJID(p); err == nil {
							senderJID = pj
						}
					}
					before := len(st.messages)
					st.recordMessage(ctx, chatJID, chatName, key.GetID(), ts, senderJID, wm.GetPushName(), fromMe, wm.GetMessage())
					if len(st.messages) > before {
						added++
					}
				}
			}
			st.backfillNames(ctx)
			st.status = "ready"
			total := len(st.messages)
			blobs := st.historyBlobs
			st.mu.Unlock()
			if err := st.flushSnapshot(); err != nil {
				log.Printf("flush snapshot error: %v", err)
			}
			log.Printf("history sync blob #%d (%s): +%d msgs in window (total %d msgs)", blobs, data.GetSyncType().String(), added, total)
		case *events.Message:
			st.mu.Lock()
			st.recordMessage(ctx, v.Info.Chat, "", v.Info.ID, v.Info.Timestamp.Unix(), v.Info.Sender, v.Info.PushName, v.Info.IsFromMe, v.Message)
			st.mu.Unlock()
			_ = st.flushSnapshot()
		case *events.LoggedOut:
			st.mu.Lock()
			st.status = "logged_out"
			st.pairedJID = ""
			st.mu.Unlock()
			log.Printf("device logged out from phone")
		}
	})

	// Periodic flush safety net.
	go func() {
		tick := time.NewTicker(5 * time.Second)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-tick.C:
				_ = st.flushSnapshot()
			}
		}
	}()

	// Helper to ensure an active pairing session (auto-restarts on QR timeout).
	var pairLoopMu sync.Mutex
	pairLoopRunning := false
	startPairing := func() {
		pairLoopMu.Lock()
		if pairLoopRunning || client.Store.ID != nil {
			pairLoopMu.Unlock()
			return
		}
		pairLoopRunning = true
		pairLoopMu.Unlock()
		go func() {
			defer func() {
				pairLoopMu.Lock()
				pairLoopRunning = false
				pairLoopMu.Unlock()
			}()
			for ctx.Err() == nil && client.Store.ID == nil {
				if client.IsConnected() {
					client.Disconnect()
					time.Sleep(500 * time.Millisecond)
				}
				qrChan, err := client.GetQRChannel(ctx)
				if err != nil {
					log.Printf("get qr channel: %v", err)
					time.Sleep(3 * time.Second)
					continue
				}
				if err := client.Connect(); err != nil {
					log.Printf("connect: %v", err)
					time.Sleep(3 * time.Second)
					continue
				}
				done := false
				for evt := range qrChan {
					switch evt.Event {
					case "code":
						png, err := qrcode.Encode(evt.Code, qrcode.Medium, 280)
						if err == nil {
							st.mu.Lock()
							st.status = "awaiting_pair"
							st.qrPNGDataURI = "data:image/png;base64," + base64.StdEncoding.EncodeToString(png)
							st.qrUpdatedAt = time.Now()
							st.mu.Unlock()
						}
					case "success":
						st.mu.Lock()
						st.status = "paired_syncing"
						st.qrPNGDataURI = ""
						st.mu.Unlock()
						done = true
					case "timeout":
						st.mu.Lock()
						st.status = "refreshing_qr"
						st.qrPNGDataURI = ""
						st.mu.Unlock()
					}
				}
				if done || client.Store.ID != nil {
					return
				}
				time.Sleep(2 * time.Second)
			}
		}()
	}

	// Connect WhatsApp (if unpaired, stream QR events with auto-refresh).
	if client.Store.ID == nil {
		startPairing()
	} else {
		st.mu.Lock()
		st.pairedJID = client.Store.ID.User
		st.status = "reconnecting"
		st.mu.Unlock()
		if err := client.Connect(); err != nil {
			log.Fatalf("connect existing session: %v", err)
		}
	}

	mux := http.NewServeMux()
	prefix := "/pair/" + token

	mux.HandleFunc(prefix, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != prefix {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		fmt.Fprintf(w, `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Idli WhatsApp Read-Only Pairing</title>
<style>
body{font-family:system-ui,sans-serif;max-width:480px;margin:2rem auto;padding:0 1rem;color:#111;line-height:1.5}
.card{border:1px solid #ddd;border-radius:10px;padding:1.25rem;margin:1rem 0}
.code{font-size:2rem;letter-spacing:0.25rem;font-weight:700;font-family:monospace;background:#f4f4f5;padding:0.75rem;border-radius:8px;text-align:center}
input,button{font-size:1rem;padding:0.5rem 0.75rem;border-radius:6px;border:1px solid #ccc}
button{background:#111;color:#fff;border:none;cursor:pointer}
.muted{color:#555;font-size:0.9rem}
img.qr{display:block;margin:0.75rem auto;border:1px solid #eee;border-radius:8px}
</style></head><body>
<h2>Link WhatsApp (Read-Only)</h2>
<p class="muted">Last %d days only. Never sends messages or read receipts. Revoke anytime in WhatsApp &rarr; Linked Devices.</p>
<div class="card" id="status">Loading status...</div>
<div class="card" id="pair-box" style="display:none">
  <h3>Option 1: Scan QR code</h3>
  <div id="qr-wrap"><p class="muted">Waiting for QR...</p></div>
  <hr style="border:none;border-top:1px solid #eee;margin:1.25rem 0">
  <h3>Option 2: 8-digit phone code (single-phone friendly)</h3>
  <form id="phone-form">
    <input id="phone" placeholder="919876543210 (country code + number)" style="width:70%%" required>
    <button type="submit">Get code</button>
  </form>
  <div id="code-wrap" style="margin-top:0.75rem"></div>
</div>
<script>
const base = %q;
async function poll() {
  try {
    const r = await fetch(base + '/status');
    const s = await r.json();
    let html = '<b>Status:</b> ' + s.status;
    if (s.paired) {
      html += '<br><b>Captured (last ' + s.window_days + 'd):</b> ' + s.messages + ' messages across ' + s.groups + ' groups, ' + s.dms + ' DMs (history blobs: ' + s.history_blobs + ')';
      if (s.earliest) html += '<br><b>Coverage:</b> ' + s.earliest + ' &rarr; ' + s.latest;
    }
    document.getElementById('status').innerHTML = html;
    document.getElementById('pair-box').style.display = s.paired ? 'none' : 'block';
    if (s.qr_png) {
      document.getElementById('qr-wrap').innerHTML = '<img class="qr" src="' + s.qr_png + '" alt="WhatsApp QR">';
    }
    if (s.pair_code) {
      document.getElementById('code-wrap').innerHTML = '<div class="code">' + s.pair_code + '</div><p class="muted">In WhatsApp: Linked Devices &rarr; Link a Device &rarr; Link with phone number instead.</p>';
    } else if (s.pair_error) {
      document.getElementById('code-wrap').innerHTML = '<p style="color:#b91c1c">' + s.pair_error + '</p>';
    }
  } catch (e) {}
}
document.getElementById('phone-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const phone = document.getElementById('phone').value;
  document.getElementById('code-wrap').innerHTML = '<p class="muted">Requesting code...</p>';
  await fetch(base + '/pair-phone', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({phone})});
  poll();
});
poll();
setInterval(poll, 2000);
</script></body></html>`, *days, html.EscapeString(prefix))
	})

	mux.HandleFunc(prefix+"/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(st.stats())
	})

	mux.HandleFunc(prefix+"/pair-phone", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			Phone string `json:"phone"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad json", http.StatusBadRequest)
			return
		}
		digits := digitsRe.ReplaceAllString(req.Phone, "")
		if len(digits) < 8 || len(digits) > 15 {
			st.mu.Lock()
			st.pairErr = "Enter digits only with country code (e.g. 919876543210)."
			st.mu.Unlock()
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if !client.IsConnected() {
			startPairing()
			for i := 0; i < 20 && !client.IsConnected(); i++ {
				time.Sleep(250 * time.Millisecond)
			}
		}
		code, err := client.PairPhone(ctx, digits, true, whatsmeow.PairClientChrome, "Chrome (Linux)")
		st.mu.Lock()
		if err != nil {
			st.pairErr = "PairPhone failed: " + err.Error()
			st.pairCode = ""
		} else {
			st.pairCode = code
			st.pairErr = ""
		}
		st.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(st.stats())
	})

	srv := &http.Server{Addr: *listenAddr, Handler: mux}
	go func() {
		log.Printf("Read-only WhatsApp pairing UI ready at: %s", urlStr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("http: %v", err)
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	log.Printf("shutting down, flushing snapshot...")
	_ = st.flushSnapshot()
	client.Disconnect()
	_ = srv.Shutdown(context.Background())
}
