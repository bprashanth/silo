"""ASR engines behind one interface: Engine.transcribe(list[np.float32 16k], prompt=None) -> list[str].

`prompt` is optional context (the question the agent just asked, domain words); engines that
can't use it ignore it. Each engine is created lazily by name with make(name).
"""
import os, json, base64, io
from pathlib import Path
import numpy as np

ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust'))
M = ART / 'models'
DOMAIN = ('Livestock helpline in Karnataka. Words: cow, buffalo, goat, sheep, calf, bullock, hen, pig, '
          'loose motions, bloated, fever, udder, foam, limping, injection, taluk, district, village.')


def _read_hf_token():
    cfg = Path.home() / '.config/idlisseus/hf.json'
    data = json.loads(cfg.read_text())
    tok = str(data.get('api_key') or '').strip()
    if not tok:
        raise RuntimeError(f'Missing api_key in {cfg}')
    return tok


def _glob_any(path, patterns):
    p = Path(path)
    return any(any(p.glob(pattern)) for pattern in patterns)


def _ensure_snapshot(local_dir, repo_id, required_files=(), required_any=()):
    """Ensure local_dir has required files; otherwise download snapshot from HF."""
    local_dir = Path(local_dir)
    missing = (
        (not local_dir.exists())
        or any(not (local_dir / req).exists() for req in required_files)
        or any(not _glob_any(local_dir, group) for group in required_any)
    )
    if missing:
        from huggingface_hub import snapshot_download

        local_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
            token=_read_hf_token(),
            resume_download=True,
        )
    bad = []
    for req in required_files:
        if not (local_dir / req).exists():
            bad.append(req)
    for group in required_any:
        if not _glob_any(local_dir, group):
            bad.append('any of: ' + ', '.join(group))
    if bad:
        raise RuntimeError(f'Incomplete model dir {local_dir} for {repo_id}; missing {bad}')
    return local_dir


def _load_domain_phrases(path, include_sections=None):
    """Flatten selected domain_terms.json sections into a deduplicated phrase list."""
    data = json.loads(Path(path).read_text())
    allowed = set(include_sections) if include_sections else None
    out, seen = [], set()
    for key, terms in data.items():
        if allowed and key not in allowed:
            continue
        if not isinstance(terms, list):
            continue
        for phrase in terms:
            p = str(phrase).strip()
            if not p:
                continue
            k = p.casefold()
            if k in seen:
                continue
            seen.add(k)
            out.append(p)
    return out

class Engine:
    name = '?'
    def transcribe(self, audios, prompt=None): raise NotImplementedError

class FasterWhisper(Engine):
    """CTranslate2 Whisper on CPU (what the POC and Telegram bot use)."""
    def __init__(self, path, beam=1, threads=8):
        from faster_whisper import WhisperModel
        self.m = WhisperModel(path, device='cpu', compute_type='int8', cpu_threads=threads); self.beam = beam
    def transcribe(self, audios, prompt=None):
        out = []
        for a in audios:
            segs, _ = self.m.transcribe(a, language='en', beam_size=self.beam, vad_filter=False,
                                        condition_on_previous_text=False, initial_prompt=prompt)
            out.append(' '.join(s.text.strip() for s in segs).strip())
        return out

class HFWhisper(Engine):
    """Transformers Whisper on the GPU, fp16."""
    def __init__(self, path, beam=1):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        self.p = WhisperProcessor.from_pretrained(str(path), local_files_only=True)
        self.m = WhisperForConditionalGeneration.from_pretrained(
            str(path),
            torch_dtype=torch.float16,
            local_files_only=True,
        ).cuda().eval()
        self.beam = beam
    def transcribe(self, audios, prompt=None):
        t = self.torch; out = []
        for a in audios:
            f = self.p(a, sampling_rate=16000, return_tensors='pt').input_features.cuda().half()
            kw = dict(language='en', task='transcribe', num_beams=self.beam, max_new_tokens=200)
            if prompt: kw['prompt_ids'] = self.p.get_prompt_ids(prompt)
            with t.inference_mode(): ids = self.m.generate(f, **kw)
            txt = self.p.batch_decode(ids, skip_special_tokens=True)[0]
            out.append(txt.strip())
        return out

class NemoASR(Engine):
    """NeMo Parakeet / Canary on the GPU. Optional word boosting for domain terms."""
    def __init__(
        self,
        path,
        canary=False,
        boost_phrases=None,
        boost_context_score=1.0,
        boost_depth_scaling=2.0,
        boost_alpha=1.0,
    ):
        import torch, nemo.collections.asr as nemo_asr
        self.torch = torch
        self.m = nemo_asr.models.ASRModel.restore_from(str(path), map_location='cuda').eval()
        self.canary = canary
        if not canary:
            try:
                from omegaconf import open_dict
                cfg = self.m.cfg.decoding
                with open_dict(cfg):
                    cfg.strategy = 'greedy_batch'
                    if boost_phrases:
                        cfg.greedy.boosting_tree = {
                            'key_phrases_list': boost_phrases,
                            'context_score': float(boost_context_score),
                            'depth_scaling': float(boost_depth_scaling),
                            'source_lang': 'en',
                            'use_triton': True,
                        }
                        cfg.greedy.boosting_tree_alpha = float(boost_alpha)
                self.m.change_decoding_strategy(cfg)
            except Exception as e:
                if boost_phrases:
                    raise RuntimeError(f'Failed to enable NeMo boosting tree: {e}') from e
                pass
    def transcribe(self, audios, prompt=None):
        kw = dict(batch_size=8, verbose=False)
        if self.canary: kw.update(source_lang='en', target_lang='en', pnc='yes')
        with self.torch.inference_mode():
            hyps = self.m.transcribe([a for a in audios], **kw)
        return [(h.text if hasattr(h, 'text') else str(h)).strip() for h in hyps]

class CanaryQwen(Engine):
    """Canary-Qwen-2.5B SALM: FastConformer encoder + Qwen LLM decoder; accepts a text prompt."""
    def __init__(self, path):
        import torch
        from nemo.collections.speechlm2.models import SALM
        self.torch = torch
        self.m = SALM.from_pretrained(str(path)).bfloat16().cuda().eval()
    def transcribe(self, audios, prompt=None):
        t = self.torch; out = []
        for a in audios:
            q = f'Transcribe the following: {self.m.audio_locator_tag}'
            if prompt: q = f'Context: {prompt}\n\n{q}'
            x = t.tensor(a, dtype=t.float32).unsqueeze(0).cuda()
            n = t.tensor([len(a)], dtype=t.long).cuda()
            with t.inference_mode():
                ids = self.m.generate(
                    prompts=[[{'role': 'user', 'content': q}]],
                    audios=x,
                    audio_lens=n,
                    max_new_tokens=200,
                    do_sample=False,
                )
            hyp_ids = ids[0].detach().cpu()
            eos = (hyp_ids == self.m.text_eos_id).nonzero(as_tuple=True)[0]
            if eos.numel():
                hyp_ids = hyp_ids[: int(eos[0])]
            out.append(self.m.tokenizer.ids_to_text(hyp_ids).strip())
        return out

class VoxtralMini(Engine):
    """Voxtral-Mini-3B-2507 in transcription-request mode via transformers."""
    def __init__(self, path, model_id='mistralai/Voxtral-Mini-3B-2507'):
        import torch
        from transformers.tokenization_mistral_common import MistralCommonBackend
        from transformers import VoxtralForConditionalGeneration, AutoProcessor

        self.torch = torch
        self.model_id = model_id
        self.p = AutoProcessor.from_pretrained(str(path), local_files_only=True, fix_mistral_regex=True)
        # AutoProcessor can resolve to a plain TokenizersBackend on this stack; force mistral-common backend
        # so `apply_transcription_request()` can build the OpenAI-style transcription request tokens.
        self.p.tokenizer = MistralCommonBackend.from_pretrained(str(path), local_files_only=True)
        self.m = VoxtralForConditionalGeneration.from_pretrained(
            str(path),
            torch_dtype=torch.bfloat16,
            device_map='cuda',
            local_files_only=True,
        ).eval()

    def transcribe(self, audios, prompt=None):
        t = self.torch
        out = []
        for a in audios:
            inputs = self.p.apply_transcription_request(
                language='en',
                audio=a,
                format='wav',
                sampling_rate=16000,
                model_id=self.model_id,
            )
            moved = {}
            for k, v in dict(inputs).items():
                if hasattr(v, 'to'):
                    v = v.to('cuda')
                    if k == 'input_features':
                        v = v.to(dtype=t.bfloat16)
                moved[k] = v
            with t.inference_mode():
                ids = self.m.generate(**moved, max_new_tokens=200, do_sample=False)
            prompt_len = moved['input_ids'].shape[1]
            txt = self.p.batch_decode(ids[:, prompt_len:], skip_special_tokens=True)[0]
            out.append(txt.strip())
        return out

class OpenRouterAudio(Engine):
    """Hosted multimodal model as a transcriber (non-private; synthetic/public audio only)."""
    def __init__(self, model):
        import requests, soundfile as sf
        self.requests, self.sf, self.model = requests, sf, model
        self.key = json.load(open(Path.home() / '.config/idlisseus/openrouter.json'))['api_key']
        self.cost = 0.0
    def transcribe(self, audios, prompt=None):
        out = []
        for a in audios:
            b = io.BytesIO(); self.sf.write(b, a, 16000, format='WAV', subtype='PCM_16')
            instr = ('Transcribe this phone audio of an Indian farmer speaking English, verbatim. '
                     'Output only the words spoken, no commentary. If nothing intelligible, output nothing.')
            if prompt: instr += ' Context: ' + prompt
            r = self.requests.post('https://openrouter.ai/api/v1/chat/completions', timeout=60,
                headers={'Authorization': 'Bearer ' + self.key},
                json={'model': self.model, 'temperature': 0, 'usage': {'include': True},
                      'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': instr},
                        {'type': 'input_audio', 'input_audio': {'data': base64.b64encode(b.getvalue()).decode(), 'format': 'wav'}}]}]})
            r.raise_for_status(); d = r.json()
            self.cost += float(d.get('usage', {}).get('cost') or 0)
            out.append((d['choices'][0]['message'].get('content') or '').strip())
        return out

def make(name):
    hf = Path.home() / '.local/share/idli-bridge/models/whisper/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots'
    domain_terms = Path(__file__).with_name('domain_terms.json')
    full_boost = _load_domain_phrases(domain_terms)
    vocab_boost = _load_domain_phrases(domain_terms, include_sections=('animals', 'symptoms', 'treatment'))

    def ensure_parakeet_v2_nemo():
        d = _ensure_snapshot(
            M / 'parakeet-tdt-0.6b-v2',
            'nvidia/parakeet-tdt-0.6b-v2',
            required_files=('parakeet-tdt-0.6b-v2.nemo',),
        )
        return d / 'parakeet-tdt-0.6b-v2.nemo'

    def ensure_whisper_v3_dir():
        return _ensure_snapshot(
            M / 'whisper-large-v3',
            'openai/whisper-large-v3',
            required_files=('config.json', 'preprocessor_config.json', 'tokenizer.json'),
            required_any=(('model.safetensors', 'model-*.safetensors', 'pytorch_model.bin', 'pytorch_model-*.bin'),),
        )

    def ensure_oriserve_dir():
        return _ensure_snapshot(
            M / 'Whisper-Hindi2Hinglish-Apex',
            'Oriserve/Whisper-Hindi2Hinglish-Apex',
            required_files=('config.json', 'preprocessor_config.json', 'tokenizer.json'),
            required_any=(('model.safetensors', 'model-*.safetensors', 'pytorch_model.bin', 'pytorch_model-*.bin'),),
        )

    def ensure_canary_qwen_dir():
        return _ensure_snapshot(
            M / 'canary-qwen-2.5b',
            'nvidia/canary-qwen-2.5b',
            required_files=('config.json', 'model.safetensors'),
        )

    def ensure_voxtral_dir():
        return _ensure_snapshot(
            M / 'Voxtral-Mini-3B-2507',
            'mistralai/Voxtral-Mini-3B-2507',
            required_files=('config.json', 'preprocessor_config.json', 'tekken.json'),
            required_any=(('consolidated.safetensors', 'model.safetensors', 'model-*.safetensors'),),
        )

    def parakeet_v3_boost():
        return NemoASR(
            M / 'parakeet-tdt-0.6b-v3/parakeet-tdt-0.6b-v3.nemo',
            boost_phrases=full_boost,
            boost_context_score=float(os.getenv('VR_PARAKEET_BOOST_CONTEXT_SCORE', '1.6')),
            boost_depth_scaling=float(os.getenv('VR_PARAKEET_BOOST_DEPTH_SCALING', '2.5')),
            boost_alpha=float(os.getenv('VR_PARAKEET_BOOST_ALPHA', '0.9')),
        )

    def parakeet_v3_boost_vocab():
        return NemoASR(
            M / 'parakeet-tdt-0.6b-v3/parakeet-tdt-0.6b-v3.nemo',
            boost_phrases=vocab_boost,
            boost_context_score=float(os.getenv('VR_PARAKEET_BOOST_CONTEXT_SCORE', '1.6')),
            boost_depth_scaling=float(os.getenv('VR_PARAKEET_BOOST_DEPTH_SCALING', '2.5')),
            boost_alpha=float(os.getenv('VR_PARAKEET_BOOST_ALPHA', '0.9')),
        )

    def parakeet_v2_boost():
        return NemoASR(
            ensure_parakeet_v2_nemo(),
            boost_phrases=full_boost,
            boost_context_score=float(os.getenv('VR_PARAKEET_BOOST_CONTEXT_SCORE', '1.6')),
            boost_depth_scaling=float(os.getenv('VR_PARAKEET_BOOST_DEPTH_SCALING', '2.5')),
            boost_alpha=float(os.getenv('VR_PARAKEET_BOOST_ALPHA', '0.9')),
        )

    table = {
        'fw-base.en-cpu': lambda: FasterWhisper('/mnt/seagate/silo/livestock-voice/models/whisper-base.en'),
        'fw-turbo-cpu': lambda: FasterWhisper(str(next(hf.iterdir()))),
        'hf-whisper-turbo-gpu': lambda: HFWhisper(M / 'whisper-large-v3-turbo'),
        'hf-whisper-v3-gpu': lambda: HFWhisper(ensure_whisper_v3_dir()),
        'hf-whisper-v3-gpu-b5': lambda: HFWhisper(ensure_whisper_v3_dir(), beam=5),
        'hf-oriserve-apex-gpu': lambda: HFWhisper(ensure_oriserve_dir()),
        'parakeet-v2': lambda: NemoASR(ensure_parakeet_v2_nemo()),
        'parakeet-v2-boost': parakeet_v2_boost,
        'parakeet-v3': lambda: NemoASR(M / 'parakeet-tdt-0.6b-v3/parakeet-tdt-0.6b-v3.nemo'),
        'parakeet-v3-boost': parakeet_v3_boost,
        'parakeet-v3-boost-vocab': parakeet_v3_boost_vocab,
        'canary-1b-v2': lambda: NemoASR(M / 'canary-1b-v2/canary-1b-v2.nemo', canary=True),
        'canary-qwen-2.5b': lambda: CanaryQwen(ensure_canary_qwen_dir()),
        'voxtral-mini-3b': lambda: VoxtralMini(ensure_voxtral_dir()),
    }
    if name.startswith('or:'): return OpenRouterAudio(name[3:])
    e = table[name](); e.name = name; return e
