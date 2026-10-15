"""Explicitly hosted, synthetic-only speech-to-speech benchmark adapter.

OpenRouter accepts a complete WAV turn then streams 24 kHz mono signed PCM16.
It is not a realtime microphone API. Never log credentials or request headers.
"""
import base64
import json
import os
import time
from pathlib import Path
import aiohttp

MODEL = 'openai/gpt-audio-mini'
KEY_PATH = Path(os.environ.get('LIVESTOCK_OPENROUTER_CONFIG', '~/.config/idlisseus/openrouter.json')).expanduser()

class OpenRouterAudio:
    model = MODEL

    async def stream(self, wav_bytes, history, system_prompt):
        """Yield dict events: transcript_delta, audio(PCM), usage, done.

        history contains prior role/content text only (locally transcribed caller
        utterances and actual generated audio transcripts). Current WAV is sent
        as input_audio, never replaced by text.
        """
        key = json.loads(KEY_PATH.read_text()).get('api_key')
        if not key:
            raise RuntimeError('OpenRouter api_key missing from configured secret file')
        content = ([{'type': 'input_audio', 'input_audio': {
            'data': base64.b64encode(wav_bytes).decode(), 'format': 'wav'}}]
            if wav_bytes else 'Begin with a brief greeting and ask what happened to the animal.')
        messages = [{'role': 'system', 'content': system_prompt}] + [
            {'role': m['role'], 'content': m['content']} for m in history
        ] + [{'role': 'user', 'content': content}]
        payload = {'model': self.model, 'messages': messages, 'modalities': ['text', 'audio'],
                   'audio': {'voice': 'alloy', 'format': 'pcm16'}, 'stream': True,
                   'stream_options': {'include_usage': True}, 'max_tokens': 512,
                   'temperature': 0.5}
        start = time.monotonic()
        first_audio_ms = None
        first_text_ms = None
        usage = {}
        transcript = ''
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as client:
            async with client.post('https://openrouter.ai/api/v1/chat/completions',
                                   headers={'Authorization': f'Bearer {key}'}, json=payload) as response:
                if response.status != 200:
                    # Provider response bodies can echo requests: don't expose them.
                    raise RuntimeError(f'OpenRouter audio HTTP {response.status}')
                async for raw in response.content:
                    line = raw.decode().strip()
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        break
                    event = json.loads(data)
                    if event.get('error'):
                        raise RuntimeError('OpenRouter audio stream returned provider error')
                    if event.get('usage'):
                        usage = event['usage']
                        yield {'type': 'usage', 'usage': usage, 'observed_cost_usd': usage.get('cost')}
                    for choice in event.get('choices', []):
                        delta = choice.get('delta', {})
                        audio = delta.get('audio') or {}
                        part = audio.get('transcript') or delta.get('content') or ''
                        if part:
                            transcript += part
                            if first_text_ms is None:
                                first_text_ms = (time.monotonic()-start)*1000
                            yield {'type': 'transcript_delta', 'text': part}
                        if audio.get('data'):
                            if first_audio_ms is None:
                                first_audio_ms = (time.monotonic()-start)*1000
                            yield {'type': 'audio', 'pcm': base64.b64decode(audio['data']), 'sample_rate': 24000}
        if first_audio_ms is None:
            raise RuntimeError('OpenRouter returned no audio; candidate unavailable')
        yield {'type': 'done', 'text': transcript, 'usage': usage,
               'observed_cost_usd': usage.get('cost'),
               'timing': {'hosted_first_audio_ms': first_audio_ms, 'hosted_first_text_ms': first_text_ms,
                          'hosted_total_ms': (time.monotonic()-start)*1000,
                          'asr_ms': None, 'llm_ms': None, 'tts_ms': None}}
