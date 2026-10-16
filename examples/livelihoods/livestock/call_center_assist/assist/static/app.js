// Operator console: WebRTC mic to the server, Lakshmamma's audio back, the care record filled live by polling.
const $ = id => document.getElementById(id);
const LABELS = {animal_type: 'Animal', symptoms: 'Problem', can_stand: 'Can stand', breathing_ok: 'Breathing normal',
  animals_affected: 'Animals sick', symptoms_since: 'Since', previous_treatment: 'Treatment given',
  caller_name: 'Farmer name', village: 'Village', district: 'District', contact_details: 'Phone'};
const STATE = {confirmed: 'confirmed', operator: 'you said', heard_only: 'heard only', operator_differs: 'differs', edited: 'edited'};
const BOOL = new Set(['can_stand', 'breathing_ok']);
let selectedAdvisory = null, lastCardsHTML = '', lastTranscriptHTML = '', ending = false;
let editing = null;  // the field being typed in: polling leaves the record alone meanwhile
let pc, ctx, sid, poll, clock, started, last = null, micStream, fixtureDest, CFG;
const TEST = new URLSearchParams(location.search).has('test');  // automated runs: test audio and the recorded-only scenarios

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])); }
function fmt(v) { if (Array.isArray(v)) return v.join(', '); if (v === true) return 'yes'; if (v === false) return 'no'; return v ?? ''; }

async function init() {
  CFG = await api('/api/config');
  CFG.cases.forEach((c, i) => $('case').add(new Option(c.opening, c.id)));
  if (TEST) for (const [k, v] of Object.entries(CFG.recorded_only)) $('case').add(new Option('(recorded only) ' + v, 'rec:' + k));
  $('fixture-box').hidden = !TEST;
  if (!CFG.ai) $('mode').value = 'recorded';
  $('fixture').onchange = loadFixtures; $('case').onchange = $('mode').onchange = modeNote; modeNote();
}

function modeNote() {
  const id = $('case').value, c = CFG.cases.find(x => x.id === id), recOnly = id.startsWith('rec:');
  const canRec = recOnly || c?.recorded, canAi = CFG.ai && !recOnly;
  $('mode').options[0].disabled = !canAi; $('mode').options[1].disabled = !canRec;
  if ($('mode').value === 'ai' && !canAi) $('mode').value = 'recorded';
  if ($('mode').value === 'recorded' && !canRec) $('mode').value = 'ai';
  $('modenote').textContent = $('mode').value === 'ai'
    ? 'An AI plays the farmer for this practice call. No real farmer or veterinary dispatch is involved.'
    : 'Recorded farmer replies for a repeatable practice call.';
}

async function loadFixtures() {
  const box = $('fixtures'); box.hidden = !$('fixture').checked; box.innerHTML = '';
  if (!$('fixture').checked) return;
  try {
    const list = await (await fetch('/clips/operator/index.json')).json();
    for (const f of list) { const b = document.createElement('button'); b.textContent = f.label; b.title = f.text; b.onclick = () => speakFixture(f.file); box.append(b); }
  } catch (e) { box.textContent = 'No operator test clips (run assist/make_scenarios.py).'; }
}

async function micOrFixture() {
  if (!$('fixture').checked)
    return navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}});
  fixtureDest = ctx.createMediaStreamDestination();
  const noise = ctx.createBufferSource(), nb = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate), d = nb.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * 0.0005;
  noise.buffer = nb; noise.loop = true; noise.connect(fixtureDest); noise.start();
  return fixtureDest.stream;
}

window.speakFixture = async function (file) {
  const buf = await ctx.decodeAudioData(await (await fetch(file.startsWith('/') ? file : '/clips/operator/' + file)).arrayBuffer());
  const src = ctx.createBufferSource(); src.buffer = buf; src.connect(fixtureDest);
  return new Promise(res => { src.onended = () => res(buf.duration); src.start(); });
};
window.playClip = url => new Audio(url).play();

async function startCall() {
  $('call').disabled = true; $('status').textContent = 'connecting'; $('review').hidden = true; $('error').hidden = true;
  selectedAdvisory = null; lastCardsHTML = ''; lastTranscriptHTML = ''; last = null; sid = null;
  $('transcript').innerHTML = '<p class=muted>Connecting the practice call.</p>'; $('fields').innerHTML = '';
  renderProtocol(null); $('urgent').hidden = true; $('record-progress').textContent = ''; $('timer').textContent = '00:00';
  $('setup').open = false; $('case').disabled = $('mode').disabled = true;
  ctx = new AudioContext({sampleRate: 48000});
  const id = $('case').value;
  const s = await api('/api/sessions', id.startsWith('rec:') ? {scenario: id.slice(4), mode: 'recorded', fixture: $('fixture').checked}
    : {case: id, mode: $('mode').value, fixture: $('fixture').checked});
  sid = s.id; window.currentSessionId = sid;
  micStream = await micOrFixture();
  pc = new RTCPeerConnection({iceServers: []});
  pc.createDataChannel('chat');  // SmallWebRTC signals over this
  micStream.getAudioTracks().forEach(t => pc.addTrack(t, micStream));
  pc.ontrack = e => { $('remote').srcObject = e.streams[0]; };
  const offer = await pc.createOffer(); await pc.setLocalDescription(offer);
  await new Promise(r => { if (pc.iceGatheringState === 'complete') r(); pc.onicegatheringstatechange = () => pc.iceGatheringState === 'complete' && r(); setTimeout(r, 1500); });
  const ans = await api(`/api/offer?session_id=${sid}`, {sdp: pc.localDescription.sdp, type: pc.localDescription.type});
  await pc.setRemoteDescription(ans);
  started = Date.now(); clock = setInterval(() => { const t = Math.floor((Date.now() - started) / 1000); $('timer').textContent = `${String(t / 60 | 0).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; }, 500);
  poll = setInterval(refresh, 300); $('end').disabled = false;
}

async function endCall() {
  if (ending) return; ending = true; clearInterval(poll);
  $('end').disabled = true; clearInterval(clock); $('status').textContent = 'reviewing';
  micStream?.getTracks().forEach(t => t.stop()); pc?.close(); pc = null;
  if (sid) { last = await api(`/api/sessions/${sid}/end`, {}); render(last); }
  clearInterval(poll); ctx?.close(); $('call').disabled = false;
  $('case').disabled = $('mode').disabled = false; ending = false;
}

async function refresh() {
  if (!sid) return;
  try { last = await api(`/api/sessions/${sid}`); render(last); if (last.status === 'ended' && pc) endCall(); } catch (e) {}
}

function render(s) {
  $('status').textContent = s.farmer_speaking ? 'farmer speaking' : s.status; $('status').className = '';
  const t = $('transcript'), atBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 40;
  const msgs = (s.transcript || []).map(m => m.role === 'farmer'
    ? `<div class="msg farmer ${m.interrupted ? 'interrupted' : ''}"><span class="who">Farmer${m.audio ? ` <button class="play" onclick="playClip('${esc(m.audio)}')">Listen</button>` : ''}</span>${esc(m.text) || '<span class="muted">(nothing recognised)</span>'}` +
      (s.status === 'ended' && m.said ? `<span class="truth">she said: ${esc(m.said)}</span>` : '') + '</div>'
    : `<div class="msg operator"><span class="who">You</span>${esc(m.text)}</div>`);
  if (s.partial) msgs.push(`<div class="msg partial">${esc(s.partial)}</div>`);
  const transcriptHTML = msgs.join('');
  if (msgs.length && transcriptHTML !== lastTranscriptHTML) {
    t.innerHTML = transcriptHTML; lastTranscriptHTML = transcriptHTML;
    if (atBottom) t.scrollTop = t.scrollHeight;
    $('latest').hidden = atBottom;
  }
  const rec = s.record; if (!rec) return;
  // Only the record: hints about a field (a gazetteer spelling, a short phone number) sit on that field.
  const hints = {}; for (const a of (s.help?.alerts || [])) if (a.slot && a.level === 'check') (hints[a.slot] ||= []).push(a.text);
  $('urgent').hidden = !rec.urgent_warning_signs?.length;
  $('urgent').textContent = 'For veterinary review: ' + (rec.urgent_warning_signs || []).join(', ');
  const complete = Object.values(rec.fields).filter(f => f.value != null && f.value !== '' && (!Array.isArray(f.value) || f.value.length)).length;
  $('record-progress').textContent = `${complete} of ${Object.keys(LABELS).length} recorded`;
  if (editing) return;
  $('fields').innerHTML = Object.entries(LABELS).map(([k, label]) => {
    const f = rec.fields[k] || {state:'empty', value:null}; let v = esc(fmt(f.value));
    if (k === 'contact_details' && f.value) v = esc(String(f.value).replace(/(\d{5})(?=\d)/, '$1 ')) + ` <span class="small muted">${String(f.value).length}/10</span>`;
    const tag = STATE[f.state] ? `<span class="tag ${f.state}">${STATE[f.state]}</span>` : '';
    const alt = f.state === 'operator_differs' ? `<span class="small muted"> line: ${esc(fmt(f.farmer))}</span>` : '';
    const hint = (hints[k] || []).map(t => `<span class="hint">${esc(t)}</span>`).join('');
    return `<dt class="${f.state}">${label}</dt><dd class="${f.state}" data-k="${k}" data-bool="${BOOL.has(k)}">${v || '<span class="todo">to ask</span>'}${tag}${alt}${hint}${pencil(k)}</dd>`;
  }).join('') + (rec.farmer_questions?.length ? `<dt>She asked</dt><dd>${esc(rec.farmer_questions.join('; '))}</dd>` : '');
  renderProtocol(s.protocol);
  if (s.review) renderReview(s);
}

// Edit on every field: the operator types the value where recognition failed. Typed values win and say "edited".
function pencil(k) { return sid ? `<button class="edit" aria-label="Edit ${esc(LABELS[k] || k)}" onclick="editField(this)">Edit</button>` : ''; }
window.editField = function (btn) {
  const dd = btn.closest('dd'), k = dd.dataset.k, f = last?.record?.fields?.[k] ?? findCardField(k), cur = f?.value;
  editing = k;
  const input = dd.dataset.bool === 'true'
    ? `<select class="edit-input"><option value="">(clear)</option><option value="yes" ${cur === true ? 'selected' : ''}>yes</option><option value="no" ${cur === false ? 'selected' : ''}>no</option></select>`
    : `<input class="edit-input" value="${esc(cur == null ? '' : fmt(cur))}" placeholder="${k === 'symptoms' ? 'comma separated' : 'type it'}">`;
  dd.innerHTML = input + ' <button class="save">Save</button> <button class="cancel">Cancel</button><span class="small err"></span>';
  const el = dd.querySelector('.edit-input'); el.focus(); el.select?.();
  const done = async save => {
    if (save) {
      try { last = await api(`/api/sessions/${sid}/edit`, {field: k, value: el.value}); }
      catch (e) { dd.querySelector('.err').textContent = ' ' + e.message.replace(/^.*"detail":"?([^"}]*).*$/, '$1'); return; }
    }
    editing = null; render(last);
  };
  dd.querySelector('.save').onclick = () => done(true); dd.querySelector('.cancel').onclick = () => done(false);
  el.onkeydown = e => { if (e.key === 'Enter') done(true); if (e.key === 'Escape') done(false); };
};
function findCardField(k) { for (const c of last?.protocol?.cards || []) for (const f of c.fields) if (f.id === k) return f; }

// Fixed reference classes; one expanded card, explicit clearing, no clinical resolution implied.
function renderProtocol(p) {
  if (editing) return;
  const groups = p?.advisories || [], active = groups.filter(g => !g.cleared), cleared = groups.filter(g => g.cleared);
  if (!active.some(g => g.id === selectedAdvisory)) selectedAdvisory = active[0]?.id || null;
  $('advisory-count').textContent = active.length ? `${active.length} to review` : '';
  const html = active.map(g => {
    const expanded = g.id === selectedAdvisory;
    const next = g.fields.find(f => f.value == null || f.value === '' || Array.isArray(f.value) && !f.value.length);
    const title = g.level === 'E' ? 'Review first' : 'Review';
    return `<article class="advisory ${expanded ? 'active' : ''}"><button class="advisory-heading" data-advisory="${esc(g.id)}" aria-expanded="${expanded}" aria-controls="advisory-${esc(g.id)}"><strong>${esc(g.title)}</strong><span>${title}</span></button>` +
      (expanded ? `<div id="advisory-${esc(g.id)}" class="advisory-body"><dl><dt>Trigger</dt><dd class="trigger-quote">${g.triggers.map(t => `${t.side === 'farmer' ? 'Farmer' : 'Operator'}: “${esc(t.text)}”`).join('<br>')}</dd>` +
      `<dt>Ask</dt><dd class="question">${next ? esc(next.ask) : 'Key details recorded. Check them with the farmer.'}</dd><dt>Importance</dt><dd>${esc(g.importance)}</dd></dl>` +
      `<details class="card-fields"><summary>All questions and answers</summary><dl>${g.fields.map(f => `<dt>${esc(f.label)}</dt><dd data-k="${esc(f.id)}" data-bool="${f.type === 'boolean'}">${f.value != null ? esc(fmt(f.value)) : `<span class="todo">${esc(f.ask)}</span>`}${pencil(f.id)}</dd>`).join('')}</dl></details>` +
      `<details class="references"><summary>Sources (${g.sources.length})</summary>${g.sources.map(r => `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}<br>${esc(r.section)}</a>`).join('')}<p>Sources support the questions, not a diagnosis or approval of this call protocol.</p></details>` +
      `<div class="card-actions"><span class="small muted">Clear when reviewed</span><button class="clear-card" data-clear="${esc(g.id)}">Clear card</button></div></div>` : '') + '</article>';
  }).join('') || `<div class="empty small">${cleared.length ? 'All current cards cleared. New concerns will appear here.' : 'Relevant prompts appear as the farmer describes the problem.'}</div>`;
  // Polling must not collapse disclosures or replace focused buttons every 300 ms.
  if (html !== lastCardsHTML) {
    const open = [...$('cards').querySelectorAll('details[open]')].map(d => d.className);
    const oldSelected = $('cards').querySelector('[aria-expanded=true]')?.dataset.advisory;
    $('cards').innerHTML = html; lastCardsHTML = html;
    if (oldSelected === selectedAdvisory) $('cards').querySelectorAll('details').forEach(d => d.open = open.includes(d.className));
  }
  $('cleared-panel').hidden = !cleared.length; $('cleared-label').textContent = `Cleared cards (${cleared.length})`;
  const clearedHTML = cleared.map(g => `<div class="cleared-card"><span>${esc(g.title)}</span><button class="text-button" data-restore="${esc(g.id)}">Restore</button></div>`).join('');
  if ($('cleared-cards').innerHTML !== clearedHTML) $('cleared-cards').innerHTML = clearedHTML;
}
$('cards').onclick = async event => {
  const heading = event.target.closest('[data-advisory]');
  if (heading) { selectedAdvisory = heading.dataset.advisory; renderProtocol(last?.protocol); $('cards').querySelector(`[data-advisory="${selectedAdvisory}"]`)?.focus(); }
  const clear = event.target.closest('[data-clear]');
  if (clear) await setCleared(clear.dataset.clear, true, clear);
};
$('cleared-cards').onclick = async event => {
  const restore = event.target.closest('[data-restore]');
  if (restore) await setCleared(restore.dataset.restore, false, restore);
};
async function setCleared(id, cleared, button) {
  if (!sid) return;
  button.disabled = true; $('card-error').hidden = true;
  try {
    last = await api(`/api/sessions/${sid}/advisories/${id}`, {cleared});
    if (!cleared) selectedAdvisory = id;
    render(last);
    ($('cards').querySelector('[aria-expanded=true]') || $('cleared-label')).focus();
  } catch (error) { $('card-error').textContent = 'Could not update this card. Please try again.'; $('card-error').hidden = false; button.disabled = false; }
}
function showPanel(record) {
  $('record-panel').hidden = !record; $('transcript-panel').hidden = record;
  $('record-tab').setAttribute('aria-selected', String(record)); $('transcript-tab').setAttribute('aria-selected', String(!record));
}
$('record-tab').onclick = () => showPanel(true); $('transcript-tab').onclick = () => showPanel(false);
for (const id of ['record-tab', 'transcript-tab']) $(id).onkeydown = e => {
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); const record = id !== 'record-tab'; showPanel(record); $(record ? 'record-tab' : 'transcript-tab').focus(); }
};
$('latest').onclick = () => { $('transcript').scrollTop = $('transcript').scrollHeight; $('latest').hidden = true; };

function renderReview(s) {
  const r = s.review; $('review').hidden = false;
  $('qa').innerHTML = r.qa.map(q => `<li class="${q.ok ? 'ok' : 'bad'}">${q.ok ? 'Recorded:' : 'Not recorded:'} ${esc(q.check)}</li>`).join('');
  $('diff').innerHTML = r.offline.error ? `<p class="muted">Not available: ${esc(r.offline.error)}</p>`
    : (r.differences.length ? '<ul>' + r.differences.map(d => `<li><strong>${esc(LABELS[d.field])}</strong>: live "${esc(d.live ?? 'not recorded')}", re-read "${esc(d.review ?? 'not recorded')}"</li>`).join('') + '</ul>'
      : `<p class="ok">Agrees with the live record (${r.offline.ms} ms).</p>`);
  $('truth').innerHTML = Object.entries(r.truth_check).map(([k, ok]) => `<li class="${ok ? 'ok' : 'bad'}">${ok ? 'Matches:' : 'Check:'} ${esc(LABELS[k])}${ok ? '' : ` <span class="small muted">(was: ${esc(fmt(r.truth?.[k]))})</span>`}</li>`).join('');
  $('handoff').hidden = !r.handoff;
  if (r.handoff) $('handoff-body').innerHTML = `<p><strong>Veterinary review</strong> ${esc(r.handoff.label)} in the prototype rules.</p>` +
    r.handoff.cards.map(c => `<p><strong>${esc(c.title)}</strong> (${c.notifiable ? 'vet to assess reporting' : 'reported observations'}): ` +
      Object.entries(c.answers).map(([k, v]) => `${esc(k)}: ${esc(fmt(v))}`).join('; ') + `<br><span class="small muted">${esc(c.reference)}</span></p>`).join('');
  $('casesheet').hidden = !r.case;
  if (r.case) $('sheet').innerHTML = `<p>${esc(r.case.story)}</p><p class="small muted">Only if asked:</p><ul>${r.case.reveal_only_if_asked.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p class="small muted">Based on: ${esc(r.case.source)}</p>`;
  $('metrics').innerHTML = (s.metrics || []).filter(m => m.heard).map(m => `<tr><td>${m.turn}</td><td class="heard">${esc(m.heard)}</td><td>${m.asr_ms} ms</td>` +
    `<td>${esc(m.asked ?? '')}${m.farmer_clip ? ' / ' + esc(m.farmer_clip) : ''}</td><td>${m.farmer_starts_after_s != null ? m.farmer_starts_after_s.toFixed(2) + ' s' : ''}</td>` +
    `<td>${m.farmer_llm_ms != null ? m.farmer_llm_ms + ' ms' : ''}</td><td>${m.op_ms ?? ''} ms ${esc(m.op_source ?? '')}</td></tr>`).join('');
}

$('call').onclick = () => startCall().catch(e => {
  $('status').textContent = 'Not connected'; $('error').textContent = e.message; $('error').hidden = false;
  clearInterval(poll); clearInterval(clock); micStream?.getTracks().forEach(t => t.stop()); pc?.close(); pc = null; ctx?.close();
  $('call').disabled = false; $('case').disabled = $('mode').disabled = false; $('setup').open = true;
});
$('end').onclick = () => endCall().catch(e => { ending = false; $('end').disabled = false; $('error').textContent = 'Could not finish the call review. Try End call again.'; $('error').hidden = false; });
$('export').onclick = () => { if (!last) return; const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(last, null, 1)], {type: 'application/json'})); a.download = `assist-${last.id}.json`; a.click(); };
init().catch(e => { $('error').textContent = 'Unable to load the call setup. Refresh to retry.'; $('error').hidden = false; });
