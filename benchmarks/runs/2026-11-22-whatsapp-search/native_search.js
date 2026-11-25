// Run only inside the paired, offline browser, via the same verified package as snapshot.py.
async () => {
    const all = await WPP.chat.list({onlyGroups: true, ignoreGroupMetadata: true});
    const [group, duplicate] = all.filter(c => c.id.server === 'g.us' && /jam\W*buns/i.test(c.name || c.formattedTitle || ''));
    if (!group || duplicate) throw new Error('Group missing or ambiguous');
    const before = group.unreadCount;
    const counts = {};
    for (const searchTerm of ['meeting', 'include', 'young', 'bird', 'birders', 'border', 'month']) {
        const result = await WPP.whatsapp.functions.msgFindSearch({remote: group.id, searchTerm, count: 50});
        if (result.canceled || !Array.isArray(result.messages)) throw new Error('Search incomplete');
        const rows = result.messages;
        if (rows.some(m => (m.id?.remote?._serialized ?? m.id?.remote?.toString()) !== group.id._serialized))
            throw new Error('Could not verify the group of a search result');
        counts[searchTerm] = {text: rows.filter(m => m.type === 'chat').length, all: rows.length, eof: result.eof};
    }
    if (group.unreadCount !== before) throw new Error('Unread count changed');
    return counts;
}
