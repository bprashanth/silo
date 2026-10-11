#!/usr/bin/env node
// Write io's real Codex profile (codex.js writeConfig) into a CODEX_HOME, then point
// it at local Muse instead of io's proxy. io's proxy only fronts ChatGPT/OpenRouter;
// a local model needs no masking, so this is the one deliberate difference from io.
//
// usage: io_config.js <codex_home> <workspace> [wall]   (wall: offline | tools, default offline)
const fs = require('fs');
const path = require('path');
const IO = process.env.IO_APP || path.resolve(__dirname, '../../io/app/io');
const codex = require(path.join(IO, 'codex.js'));
const runtime = require(path.join(IO, 'runtime.js')).resolve();

const [home, ws, wall = 'offline'] = process.argv.slice(2);
const bin = codex.bundledCodexPath();
codex.writeConfig(home, 1, { wall, trust: ws, codexDir: bin.dir, libsDir: runtime.runtimeDir });

const cfg = path.join(home, `${codex.PROFILE}.config.toml`);
const toml = fs.readFileSync(cfg, 'utf8');
// Top-level keys must precede the first table, so insert right after io's header lines.
const base = process.env.IDLI_BASE_URL || 'http://127.0.0.1:8181/v1';
const model = process.env.IDLI_MODEL || 'muse-glimmer-30b';
const top = [`model_provider = "idli"`, `model = "${model}"`].join('\n');
const table = ['[model_providers.idli]', 'name = "idli local"', `base_url = "${base}"`,
  'wire_api = "responses"', 'requires_openai_auth = false', 'supports_websockets = false', ''].join('\n');
const i = toml.indexOf('\n[');
fs.writeFileSync(cfg, toml.slice(0, i) + '\n' + top + toml.slice(i) + '\n' + table);
console.log(JSON.stringify({ bin: bin.path, version: bin.version, libs: runtime.runtimeDir, profile: codex.PROFILE }));
