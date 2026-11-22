async ({since, until, all, cap}) => {
    const listed = await WPP.chat.list({onlyGroups: true, ignoreGroupMetadata: true});
    const active = listed.filter(c => c.id.server === 'g.us' && c.t >= since && c.t <= until);
    const title = c => c.name || c.formattedTitle || '';
    const groups = all ? active : active.filter(c => /jam\W*buns/i.test(title(c)));
    if (!all && groups.length !== 1) throw new Error('Smoke group missing or ambiguous');
    // Fresh linked sessions can have cached history without WA-JS's default lastReceivedKey.
    // Probe only key ranges whose remote ID is exactly the already selected group.
    const db = await new Promise((resolve, reject) => {
        const q = indexedDB.open('model-storage');
        q.onsuccess = () => resolve(q.result);
        q.onerror = () => reject(q.error);
    });
    async function newestText(id) {
        let newest;
        let textCount = 0;
        for (const own of ['true', 'false']) {
            const prefix = own + '_' + id + '_';
            const store = db.transaction('message', 'readonly').objectStore('message');
            await new Promise((resolve, reject) => {
                const q = store.openCursor(IDBKeyRange.bound(prefix, prefix + '\uffff'));
                q.onerror = () => reject(q.error);
                q.onsuccess = () => {
                    const cursor = q.result;
                    if (!cursor) return resolve();
                    const {id: key, t, type} = cursor.value;
                    if (type === 'chat') {
                        textCount++;
                        if (!newest || t > newest.t) newest = {key, t};
                    }
                    cursor.continue();
                };
            });
        }
        return {newest, textCount};
    }
    const results = [];
    for (const c of groups) {
        const id = c.id._serialized;
        const before = c.unreadCount;
        const result = {id, name: title(c), active_at: c.t, rows: [], fetched: 0, failed: false};
        try {
            result.stage = 'anchor';
            const {newest: anchor, textCount} = await newestText(id);
            result.cachedText = textCount;
            result.stage = 'history';
            const messages = anchor ? await WPP.chat.getMessages(id, {count: cap - 1, id: anchor.key}) : [];
            result.stage = 'newest';
            if (messages.length) {
                const near = messages.reduce((a,b) => a.t >= b.t ? a : b);
                const tail = await WPP.chat.getMessages(id, {count: 1, id: near.id._serialized, direction: 'after'});
                messages.push(...tail);
            } else if (anchor) {
                messages.push(await WPP.chat.getMessageById(anchor.key));
            }
            result.stage = 'project';
            result.fetched = messages.length;
            const seen = new Set();
            for (const m of messages) {
                if (m.id.remote?._serialized !== id) throw new Error('Group mismatch');
                if (m.type !== 'chat' || typeof m.body !== 'string' || !m.body.trim()) continue;
                const key = m.id._serialized;
                if (!key || seen.has(key)) continue;
                seen.add(key);
                const author = m.author || m.id.participant;
                const contact = author && WPP.whatsapp.ContactStore.get(author);
                const sender = m.id.fromMe ? 'Me' : (contact?.name || contact?.pushname || m.notifyName || null);
                result.rows.push({id: key, t: m.t, sender, body: m.body});
            }
            result.includesNewest = !anchor || seen.has(anchor.key);
            result.stage = 'done';
        } catch (err) {
            result.errorType = String(err.name).replace(/[^a-zA-Z]/g,'').slice(0,40);
            result.failed = true;
            result.rows = [];
        }
        if (c.unreadCount !== before) throw new Error('Unread count changed');
        results.push(result);
    }
    db.close();
    return {groups: results, active: active.length};
}
