"""Local OpenAI speech API compatibility shim for native Dograh.

No external inference. Isolated from production Telegram; reuses model files.
Bind only to Docker's gateway interface via DOGRAH_SPEECH_HOST.
"""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tg-bridge'))
import speech
from aiohttp import web, ClientSession

async def transcriptions(request):
    form = await request.post()
    audio = form['file'].file.read()
    text = await asyncio.to_thread(speech.transcribe, audio, ())
    return web.json_response({'text': text})

async def synthesize(request):
    body = await request.json()
    ogg = await asyncio.to_thread(speech.synth, body['input'], 'af_heart', 'en-us')
    fmt = body.get('response_format', 'mp3')
    fmt = {'pcm': 's16le', 'wav': 'wav', 'mp3': 'mp3', 'opus': 'ogg', 'flac': 'flac'}.get(fmt, 'mp3')
    proc = await asyncio.create_subprocess_exec('ffmpeg','-loglevel','error','-i','pipe:0','-f',fmt,'-ar','24000','-ac','1','pipe:1',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    output, _ = await proc.communicate(ogg)
    if proc.returncode:
        raise web.HTTPInternalServerError(text='Local speech encoding failed')
    return web.Response(body=output, content_type='application/octet-stream')

async def muse_proxy(request):
    url = 'http://127.0.0.1:8181' + request.path
    async with ClientSession() as client:
        async with client.request(request.method, url, data=await request.read(), headers={'Content-Type':'application/json'}) as upstream:
            response = web.StreamResponse(status=upstream.status, headers={'Content-Type':upstream.headers.get('Content-Type','application/json')})
            await response.prepare(request)
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
            return response

app = web.Application(client_max_size=20*1024**2)
app.router.add_route('*', '/v1/models', muse_proxy)
app.router.add_post('/v1/chat/completions', muse_proxy)
app.router.add_post('/v1/audio/transcriptions', transcriptions)
app.router.add_post('/v1/audio/speech', synthesize)
app.router.add_get('/health', lambda request: web.json_response({'status':'ok','privacy':'local-only'}))
if __name__ == '__main__':
    # Bound CPU parallelism in this isolated service, as in the shared local stack.
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    opts=ort.SessionOptions(); opts.intra_op_num_threads=4; opts.inter_op_num_threads=1
    model_dir=Path(speech.MODELS)/'kokoro'
    session=ort.InferenceSession(str(model_dir/'kokoro-v1.0.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
    speech._kokoro=Kokoro.from_session(session,str(model_dir/'voices-v1.0.bin'))
    web.run_app(app, host=os.environ.get('DOGRAH_SPEECH_HOST','172.17.0.1'), port=18282, access_log=None)
