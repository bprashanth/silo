// Operator console: WebRTC mic to the server, the scripted farmer's audio back, live assist by polling.
const $ = id => document.getElementById(id);
const LABELS = {animal_type: 'Animal', symptoms: 'Problem', can_stand: 'Can stand', breathing_ok: 'Breathing normal',
  animals_affected: 'Animals sick', symptoms_since: 'Since', previous_treatment: 'Treatment given',
  caller_name: 'Farmer name', village: 'Village', district: 'District', contact_details: 'Phone'};
const STATE = {confirmed: 'confirmed', operator: 'you said', heard_only: 'heard only', operator_differs: 'differs'};
let pc, ctx, sid, poll, clock, started, last = null, micStream, fixtureDest;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])); }
function fmt(v) { if (Array.isArray(v)) return v.join(', '); if (v === true) return 'yes'; if (v === false) return 'no'; return v ?? ''; }

async function init() {
  const cfg = await api('/api/config');
  for (const [k, v] of Object.entries(cfg.scenarios)) $('scenario').add(new Option(v, k));
  if (!Object.keys(cfg.scenarios).length) $('status').textContent = 'no scenarios: run assist/make_scenarios.py';
  $('fixture').onchange = loadFixtures;
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
  const buf = await ctx.decodeAudioData(await (await fetch('/clips/operator/' + file)).arrayBuffer());
  const src = ctx.createBufferSource(); src.buffer = buf; src.connect(fixtureDest);
  return new Promise(res => { src.onended = () => res(buf.duration); src.start(); });
};
window.playClip = url => new Audio(url).play();

async function startCall() {
  $('call').disabled = true; $('status').textContent = 'connecting'; $('review').hidden = true;
  ctx = new AudioContext({sampleRate: 48000});
  const s = await api('/api/sessions', {scenario: $('scenario').value, fixture: $('fixture').checked});
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
    ? `<div class="msg farmer ${m.interrupted ? 'interrupted' : ''}"><span class="who">Farmer, as the line heard it${m.audio ? ` <button class="play" onclick="playClip('${esc(m.audio)}')">▶</button>` : ''}</span>${esc(m.text) || '<span class="muted">(nothing recognised)</span>'}</div>`
    : `<div class="msg operator"><span class="who">You</span>${esc(m.text)}</div>`);
  if (s.partial) msgs.push(`<div class="msg partial">${esc(s.partial)} …</div>`);
  if (msgs.length) { t.innerHTML = msgs.join(''); if (atBottom) t.scrollTop = t.scrollHeight; }
  const h = s.help;
  if (h) {
    $('next').className = 'next ' + h.next.kind;
    $('next').innerHTML = `<span class="slot">${esc(h.next.kind === 'summary' ? 'wrap up' : (LABELS[h.next.slot] || h.next.slot) + (h.next.kind === 'repeat' ? ' · confirm' : ' · next'))}</span>${esc(h.next.text)}`;
    $('alerts').innerHTML = h.alerts.map(a => `<div class="alert ${a.level}">${esc(a.text)}</div>`).join('');
  }
  const rec = s.record; if (!rec) return;
  $('urgency').hidden = !rec.urgent_warning_signs?.length;
  const ph = rec.fields.contact_details.value;
  $('phone').hidden = !ph;
  if (ph) $('phone').textContent = String(ph).replace(/(\d{5})(?=\d)/, '$1 ') + `  (${String(ph).length}/10)`;
  $('fields').innerHTML = Object.entries(LABELS).map(([k, label]) => {
    const f = rec.fields[k];
    const tag = STATE[f.state] ? `<span class="tag ${f.state}">${STATE[f.state]}</span>` : '';
    const alt = f.state === 'operator_differs' ? `<span class="small muted"> line: ${esc(fmt(f.farmer))}</span>` : '';
    return `<dt>${label}</dt><dd>${esc(fmt(f.value)) || '—'}${tag}${alt}</dd>`;
  }).join('') + `<dt>Urgent signs</dt><dd>${esc(rec.urgent_warning_signs.join(', ') || 'none reported')}</dd>`;
  if (s.review) renderReview(s);
}

function renderReview(s) {
  const r = s.review; $('review').hidden = false;
  $('qa').innerHTML = r.qa.map(q => `<li class="${q.ok ? 'ok' : 'bad'}">${q.ok ? '✔' : '✘'} ${esc(q.check)}</li>`).join('');
  $('diff').innerHTML = r.offline.error ? `<p class="muted">Not available: ${esc(r.offline.error)}</p>`
    : (r.differences.length ? '<ul>' + r.differences.map(d => `<li><strong>${esc(LABELS[d.field])}</strong>: live "${esc(d.live ?? '—')}", re-read "${esc(d.review ?? '—')}"</li>`).join('') + '</ul>'
      : `<p class="ok">Agrees with the live record (${r.offline.ms} ms).</p>`);
  $('truth').innerHTML = Object.entries(r.truth_check).map(([k, ok]) => `<li class="${ok ? 'ok' : 'bad'}">${ok ? '✔' : '✘'} ${esc(LABELS[k])}</li>`).join('');
  $('metrics').innerHTML = (s.metrics || []).filter(m => m.heard).map(m => `<tr><td>${m.turn}</td><td class="heard">${esc(m.heard)}</td><td>${m.asr_ms} ms</td>` +
    `<td>${esc(m.asked ?? '')}${m.farmer_clip ? ' → ' + esc(m.farmer_clip) : ''}</td><td>${m.farmer_starts_after_s != null ? m.farmer_starts_after_s.toFixed(2) + ' s' : ''}</td>` +
    `<td>${m.op_ms ?? ''} ms ${esc(m.op_source ?? '')}</td></tr>`).join('');
}

$('call').onclick = () => startCall().catch(e => { $('status').textContent = 'error: ' + e.message; $('call').disabled = false; });
$('end').onclick = endCall;
$('export').onclick = () => { if (!last) return; const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(last, null, 1)], {type: 'application/json'})); a.download = `assist-${last.id}.json`; a.click(); };
init();
