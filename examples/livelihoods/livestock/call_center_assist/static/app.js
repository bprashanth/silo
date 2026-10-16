// Browser side of the call: WebRTC to the server, live view by polling, browser-side latency.
const $ = id => document.getElementById(id);
const LABELS = {animal_type: 'Animal', symptoms: 'Problem', can_stand: 'Can stand', breathing_ok: 'Breathing normal',
  animals_affected: 'Animals sick', symptoms_since: 'Since', previous_treatment: 'Treatment given',
  caller_name: 'Farmer', village: 'Village', district: 'District', contact_details: 'Phone'};
let pc, ctx, callId, poll, clock, started, last = null, micStream, fixtureDest, browserLat = [];
// Browser latency: local voice -> silence edge, then the next remote onset.
let localVoiced = false, localQuietSince = null, speechEndAt = null, remoteVoiced = false, fixtureEndAt = null;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}

async function init() {
  const cfg = await api('/api/config');
  for (const [k, v] of Object.entries(cfg.nlu)) $('nlu').add(new Option(v, k));
  $('engines').textContent = `ASR ${cfg.asr} · voice ${cfg.voice}`;
  $('fixture').onchange = loadFixtures;
}

async function loadFixtures() {
  const box = $('fixtures'); box.hidden = !$('fixture').checked; box.innerHTML = '';
  if (!$('fixture').checked) return;
  try {
    const list = await (await fetch('/fixtures/index.json')).json();
    for (const f of list) { const b = document.createElement('button'); b.textContent = f.label; b.onclick = () => speakFixture(f.file); box.append(b); }
  } catch (e) { box.textContent = 'No fixtures found (run make_fixtures.py).'; }
}

function level(analyser, buf) { analyser.getFloatTimeDomainData(buf); let s = 0; for (const v of buf) s += v * v; return Math.sqrt(s / buf.length); }

function monitor(localStream, remoteStream) {
  // Browser-side latency: end of the farmer's speech (fixture end, or 300 ms of mic quiet) to the
  // next onset of agent audio (agent audio after >= 300 ms of silence).
  const la = ctx.createAnalyser(), ra = ctx.createAnalyser(); la.fftSize = ra.fftSize = 1024;
  ctx.createMediaStreamSource(localStream).connect(la); ctx.createMediaStreamSource(remoteStream).connect(ra);
  const lb = new Float32Array(1024), rb = new Float32Array(1024);
  let remoteQuietSince = performance.now();
  (function tick() {
    if (!pc) return;
    const now = performance.now(), l = level(la, lb), r = level(ra, rb);
    if (!$('fixture').checked) {
      if (l > 0.02) { localVoiced = true; localQuietSince = null; }
      else if (localVoiced) { localQuietSince ??= now; if (now - localQuietSince > 300) { speechEndAt = localQuietSince; localVoiced = false; } }
    } else if (fixtureEndAt) { speechEndAt = fixtureEndAt; fixtureEndAt = null; }
    if (r > 0.01) {
      if (remoteQuietSince !== null && now - remoteQuietSince > 300 && speechEndAt && now > speechEndAt) {
        const ms = Math.round(now - speechEndAt); browserLat.push(ms); speechEndAt = null;
        if (callId) api(`/api/calls/${callId}/events`, {type: 'browser_first_audio', speech_end_to_audible_ms: ms}).catch(() => {});
      }
      remoteQuietSince = null;
    } else if (remoteQuietSince === null) remoteQuietSince = now;
    requestAnimationFrame(tick);
  })();
}

async function micOrFixture() {
  if (!$('fixture').checked)
    return navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}});
  // Test audio: a quiet noise bed keeps the sender alive; fixtures are mixed in on demand.
  fixtureDest = ctx.createMediaStreamDestination();
  const noise = ctx.createBufferSource(), nb = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate), d = nb.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * 0.0008;
  noise.buffer = nb; noise.loop = true; noise.connect(fixtureDest); noise.start();
  return fixtureDest.stream;
}

window.speakFixture = async function (file) {
  const buf = await ctx.decodeAudioData(await (await fetch('/fixtures/' + file)).arrayBuffer());
  const src = ctx.createBufferSource(); src.buffer = buf; src.connect(fixtureDest);
  return new Promise(res => { src.onended = () => { fixtureEndAt = performance.now(); res(buf.duration); }; src.start(); });
};

async function startCall() {
  $('call').disabled = true; $('status').textContent = 'connecting'; browserLat = [];
  ctx = new AudioContext({sampleRate: 48000});
  const c = await api('/api/calls', {nlu: $('nlu').value, line: $('line').checked, fixture: $('fixture').checked});
  callId = c.id; window.currentCallId = callId;
  micStream = await micOrFixture();
  pc = new RTCPeerConnection({iceServers: []});
  pc.createDataChannel('chat');  // SmallWebRTC signals over this
  micStream.getAudioTracks().forEach(t => pc.addTrack(t, micStream));
  pc.ontrack = e => { $('remote').srcObject = e.streams[0]; monitor(micStream, e.streams[0]); };
  const offer = await pc.createOffer(); await pc.setLocalDescription(offer);
  await new Promise(r => { if (pc.iceGatheringState === 'complete') r(); pc.onicegatheringstatechange = () => pc.iceGatheringState === 'complete' && r(); setTimeout(r, 1500); });
  const ans = await api(`/api/offer?call_id=${callId}`, {sdp: pc.localDescription.sdp, type: pc.localDescription.type});
  await pc.setRemoteDescription(ans);
  started = Date.now(); clock = setInterval(() => { const s = Math.floor((Date.now() - started) / 1000); $('timer').textContent = `${String(s / 60 | 0).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }, 500);
  poll = setInterval(refresh, 300); $('end').disabled = false;
}

async function endCall() {
  $('end').disabled = true; clearInterval(clock);
  micStream?.getTracks().forEach(t => t.stop()); pc?.close(); pc = null;
  if (callId) { last = await api(`/api/calls/${callId}/end`, {}); render(last); }
  clearInterval(poll); ctx?.close(); $('call').disabled = false;
}

async function refresh() {
  if (!callId) return;
  try { last = await api(`/api/calls/${callId}`); render(last); if (last.status === 'ended' && pc) endCall(); } catch (e) {}
}

function esc(s) { return String(s ?? '').replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c])); }

function render(c) {
  $('status').textContent = c.status; $('status').className = 'pill ' + c.status;
  const t = $('transcript'), atBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 40;
  t.innerHTML = (c.transcript || []).map(m => `<div class="msg ${m.role} ${m.kind || ''} ${m.interrupted ? 'interrupted' : ''}">` +
    (m.kind === 'ack' || m.kind === 'filler' ? '' : `<span class="who">${m.role === 'agent' ? 'Agent' : 'Farmer (as heard)'}${m.interrupted ? ' · interrupted' : ''}</span>`) +
    esc(m.text) + '</div>').join('');
  if (atBottom) t.scrollTop = t.scrollHeight;
  const rec = c.record; if (!rec) return;
  $('urgency').hidden = !rec.urgent_warning_signs?.length;
  $('fields').innerHTML = Object.entries(LABELS).map(([k, label]) => {
    const s = rec.slots[k]; let v = s.value;
    if (Array.isArray(v)) v = v.join(', '); if (v === true) v = 'yes'; if (v === false) v = 'no';
    const state = s.state === 'filled' ? '' : s.state;
    return `<dt>${label}</dt><dd class="${state}">${esc(v ?? (state ? '' : '—'))}${state && state !== 'empty' ? `<span class="state">${state}</span>` : ''}${state === 'empty' ? '—' : ''}</dd>`;
  }).join('') + `<dt>Urgent signs</dt><dd>${esc(rec.urgent_warning_signs.join(', ') || 'none reported')}</dd>` +
    `<dt>Confirmed</dt><dd>${rec.confirmed_by_caller ? 'yes' : 'not yet'}</dd><dt>Status</dt><dd>${esc(rec.call_status)}</dd>`;
  const b = [...browserLat];
  $('metrics').innerHTML = (c.metrics || []).filter(m => m.heard !== undefined).map(m => `<tr><td>${m.turn}</td><td class="heard">${esc(m.heard)}${m.cancelled ? ' <span class="muted">(merged)</span>' : ''}</td>` +
    `<td>${m.eot_s && m.speech_end_s ? ((m.eot_s - m.speech_end_s) * 1000 | 0) + ' ms' : ''}</td><td>${m.asr_ms ?? ''} ms</td>` +
    `<td>${m.nlu_ms ? m.nlu_ms + ' ms ' + esc(m.nlu_source) : ''}</td><td>${m.first_audio_after_s != null ? m.first_audio_after_s.toFixed(2) + ' s' : ''}</td>` +
    `<td>${m.response_s != null ? m.response_s.toFixed(2) + ' s' + (m.filler ? ' +filler' : '') : ''}</td><td>${m.response_s != null && b.length ? b.shift() + ' ms' : ''}</td></tr>`).join('');
}

$('call').onclick = () => startCall().catch(e => { $('status').textContent = 'error: ' + e.message; $('call').disabled = false; });
$('end').onclick = endCall;
$('export').onclick = () => { if (!last) return; const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(last, null, 1)], {type: 'application/json'})); a.download = `call-${last.id}.json`; a.click(); };
init();
