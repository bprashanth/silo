// Operator console: WebRTC mic to the server, Lakshmamma's audio back, the care record filled live by polling.
const $ = id => document.getElementById(id);
const LABELS = {animal_type: 'Animal', symptoms: 'Problem', can_stand: 'Can stand', breathing_ok: 'Breathing normal',
  animals_affected: 'Animals sick', symptoms_since: 'Since', previous_treatment: 'Treatment given',
  caller_name: 'Farmer name', village: 'Village', district: 'District', contact_details: 'Phone'};
const STATE = {confirmed: 'confirmed', operator: 'you said', heard_only: 'heard only', operator_differs: 'differs', edited: 'edited'};
const BOOL = new Set(['can_stand', 'breathing_ok']);
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
  CFG.cases.forEach((c, i) => $('case').add(new Option(`${i + 1}. "${c.opening}"${c.recorded ? '  (recorded too)' : ''}`, c.id)));
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
    ? `Live: ${CFG.llm} on OpenRouter plays Lakshmamma from the case sheet. It hears your words as recognised (synthetic role-play only); her voice is local Kokoro over a 2G line.`
    : 'Recorded: fixed clips answer the question you ask, in the checklist order. Same farmer every time.';
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
  $('call').disabled = true; $('status').textContent = 'connecting'; $('review').hidden = true;
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
  $('end').disabled = true; clearInterval(clock); $('status').textContent = 'reviewing';
  micStream?.getTracks().forEach(t => t.stop()); pc?.close(); pc = null;
  if (sid) { last = await api(`/api/sessions/${sid}/end`, {}); render(last); }
  clearInterval(poll); ctx?.close(); $('call').disabled = false;
}

async function refresh() {
  if (!sid) return;
  try { last = await api(`/api/sessions/${sid}`); render(last); if (last.status === 'ended' && pc) endCall(); } catch (e) {}
}

function render(s) {
  $('status').textContent = s.farmer_speaking ? 'farmer speaking' : s.status; $('status').className = 'pill ' + (s.farmer_speaking ? 'speaking' : '');
  const t = $('transcript'), atBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 40;
  const msgs = (s.transcript || []).map(m => m.role === 'farmer'
    ? `<div class="msg farmer ${m.interrupted ? 'interrupted' : ''}"><span class="who">Lakshmamma, as the line heard it${m.audio ? ` <button class="play" onclick="playClip('${esc(m.audio)}')">▶</button>` : ''}</span>${esc(m.text) || '<span class="muted">(nothing recognised)</span>'}` +
      (s.status === 'ended' && m.said ? `<span class="truth">she said: ${esc(m.said)}</span>` : '') + '</div>'
    : `<div class="msg operator"><span class="who">You</span>${esc(m.text)}</div>`);
  if (s.partial) msgs.push(`<div class="msg partial">${esc(s.partial)} …</div>`);
  if (msgs.length) { t.innerHTML = msgs.join(''); if (atBottom) t.scrollTop = t.scrollHeight; }
  const rec = s.record; if (!rec) return;
  // Only the record: hints about a field (a gazetteer spelling, a short phone number) sit on that field.
  const hints = {}; for (const a of (s.help?.alerts || [])) if (a.slot && a.level === 'check') (hints[a.slot] ||= []).push(a.text);
  $('urgency').hidden = !rec.urgent_warning_signs?.length;
  $('urgent').hidden = !rec.urgent_warning_signs?.length;
  $('urgent').textContent = 'Urgent: ' + (rec.urgent_warning_signs || []).join(', ');
  if (editing) return;
  $('fields').innerHTML = Object.entries(LABELS).map(([k, label]) => {
    const f = rec.fields[k]; let v = esc(fmt(f.value));
    if (k === 'contact_details' && f.value) v = esc(String(f.value).replace(/(\d{5})(?=\d)/, '$1 ')) + ` <span class="small muted">${String(f.value).length}/10</span>`;
    const tag = STATE[f.state] ? `<span class="tag ${f.state}">${STATE[f.state]}</span>` : '';
    const alt = f.state === 'operator_differs' ? `<span class="small muted"> line: ${esc(fmt(f.farmer))}</span>` : '';
    const hint = (hints[k] || []).map(t => `<span class="hint">${esc(t)}</span>`).join('');
    return `<dt class="${f.state}">${label}</dt><dd class="${f.state}" data-k="${k}" data-bool="${BOOL.has(k)}">${v || '<span class="todo">to ask</span>'}${tag}${alt}${hint}${pencil(k)}</dd>`;
  }).join('') + (rec.farmer_questions?.length ? `<dt>She asked</dt><dd>${esc(rec.farmer_questions.join('; '))}</dd>` : '');
  renderProtocol(s.protocol);
  if (s.review) renderReview(s);
}

// ✎ on every field: the operator types the value where recognition failed. Typed values win and say "edited".
function pencil(k) { return sid ? `<button class="edit" title="Edit" onclick="editField(this)">✎</button>` : ''; }
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

// Protocol cards (prototype): opened by what was said; extra questions, a priority, and lines to read out.
function renderProtocol(p) {
  if (editing) return;
  $('priority').hidden = !p; $('cards').innerHTML = '';
  if (!p) return;
  $('priority').className = 'priority lvl' + p.level;
  $('priority').innerHTML = `<strong>Priority ${p.level} · ${esc(p.label)}</strong> ${esc(p.response)}` +
    (p.escalate ? (p.escalated ? ' <span class="said">✓ done</span>' : ' <span class="todo">not yet</span>') : '');
  const said = x => x.said ? '<span class="said">✓</span>' : '<span class="todo">say</span>';
  $('cards').innerHTML = p.cards.map(c => `<div class="card"><h3>${esc(c.title)} <span class="lvl lvl${c.level}">${c.level}</span>` +
      `${c.notifiable ? ' <span class="tag operator_differs">tell the vet: notifiable?</span>' : ''}</h3><dl>` +
      c.fields.map(f => `<dt class="${f.state}">${esc(f.label)}</dt><dd class="${f.state}" data-k="${f.id}" data-bool="${f.type === 'boolean'}">${f.value != null ? esc(fmt(f.value)) +
        (STATE[f.state] ? `<span class="tag ${f.state}">${STATE[f.state]}</span>` : '') : `<span class="todo">ask: ${esc(f.ask)}</span>`}${pencil(f.id)}</dd>`).join('') +
      '</dl>' + c.say.map(x => `<div class="say">${said(x)} “${esc(x.text)}”</div>`).join('') + '</div>').join('') +
    `<div class="say closing">${said(p.closing)} Before closing: “${esc(p.closing.text)}”</div>` +
    `<p class="small muted">${esc(p.status)}</p>`;
}

function renderReview(s) {
  const r = s.review; $('review').hidden = false;
  $('qa').innerHTML = r.qa.map(q => `<li class="${q.ok ? 'ok' : 'bad'}">${q.ok ? '✔' : '✘'} ${esc(q.check)}</li>`).join('');
  $('diff').innerHTML = r.offline.error ? `<p class="muted">Not available: ${esc(r.offline.error)}</p>`
    : (r.differences.length ? '<ul>' + r.differences.map(d => `<li><strong>${esc(LABELS[d.field])}</strong>: live "${esc(d.live ?? '—')}", re-read "${esc(d.review ?? '—')}"</li>`).join('') + '</ul>'
      : `<p class="ok">Agrees with the live record (${r.offline.ms} ms).</p>`);
  $('truth').innerHTML = Object.entries(r.truth_check).map(([k, ok]) => `<li class="${ok ? 'ok' : 'bad'}">${ok ? '✔' : '✘'} ${esc(LABELS[k])}${ok ? '' : ` <span class="small muted">(was: ${esc(fmt(r.truth?.[k]))})</span>`}</li>`).join('');
  $('handoff').hidden = !r.handoff;
  if (r.handoff) $('handoff-body').innerHTML = `<p><strong>Priority ${esc(r.handoff.level)} · ${esc(r.handoff.label)}</strong> ${esc(r.handoff.response)}</p>` +
    r.handoff.cards.map(c => `<p><strong>${esc(c.title)}</strong> (${c.level}${c.notifiable ? ', possibly notifiable' : ''}): ` +
      Object.entries(c.answers).map(([k, v]) => `${esc(k)}: ${esc(fmt(v))}`).join('; ') + `<br><span class="small muted">${esc(c.reference)}</span></p>`).join('');
  $('casesheet').hidden = !r.case;
  if (r.case) $('sheet').innerHTML = `<p>${esc(r.case.story)}</p><p class="small muted">Only if asked:</p><ul>${r.case.reveal_only_if_asked.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p class="small muted">Based on: ${esc(r.case.source)}</p>`;
  $('metrics').innerHTML = (s.metrics || []).filter(m => m.heard).map(m => `<tr><td>${m.turn}</td><td class="heard">${esc(m.heard)}</td><td>${m.asr_ms} ms</td>` +
    `<td>${esc(m.asked ?? '')}${m.farmer_clip ? ' → ' + esc(m.farmer_clip) : ''}</td><td>${m.farmer_starts_after_s != null ? m.farmer_starts_after_s.toFixed(2) + ' s' : ''}</td>` +
    `<td>${m.farmer_llm_ms != null ? m.farmer_llm_ms + ' ms' : ''}</td><td>${m.op_ms ?? ''} ms ${esc(m.op_source ?? '')}</td></tr>`).join('');
}

$('call').onclick = () => startCall().catch(e => { $('status').textContent = 'error: ' + e.message; $('call').disabled = false; });
$('end').onclick = endCall;
$('export').onclick = () => { if (!last) return; const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(last, null, 1)], {type: 'application/json'})); a.download = `assist-${last.id}.json`; a.click(); };
init();
