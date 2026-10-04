import base64
import io
import wave
from types import SimpleNamespace

import pytest
from flask import Flask
from unittests.test_model_scenario_api import scenario_api_client


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(CONFUCIUS_R2T2_BACKEND='llama-cpu',
                      CONFUCIUS_T3PO_BACKEND='llama-cpu',
                      CONFUCIUS_R2T2_CPU_URL='http://127.0.0.1:8273/v1',
                      CONFUCIUS_T3PO_CPU_URL='http://127.0.0.1:8010')
    return app


def stub_completion(monkeypatch, content, finish_reason='stop'):
    from services import confucius
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'message': {'content': content}, 'finish_reason': finish_reason}]})
    monkeypatch.setattr(confucius.requests.Session, 'post', lambda self, *args, **kwargs: post(*args, **kwargs))
    return calls


@pytest.mark.parametrize('direction', ['zh2en', 'en2zh'])
def test_cpu_translation_uses_llama_protocol(app, monkeypatch, direction):
    from services.confucius import translate
    calls = stub_completion(monkeypatch, 'Hello.')
    with app.app_context():
        result = translate('你好。', direction=direction)
    assert calls[0][0] == 'http://127.0.0.1:8010/v1/chat/completions'
    payload = calls[0][1]['json']
    assert '<STREAMING_HISTORY>' in payload['messages'][1]['content']
    assert '<CURRENT_INPUT>\n你好。' in payload['messages'][1]['content']
    assert ('Chinese-to-English' if direction == 'zh2en' else 'English-to-Chinese') in payload['messages'][1]['content']
    assert payload['temperature'] == 0 and payload['stream'] is False
    assert 'min_tokens' not in payload
    assert result['text'] == 'Hello.'
    assert result['events'] == [{'type': 'translation', 'text': 'Hello.'}]
    assert result['backend'] == 'llama-cpu'


@pytest.mark.parametrize('content,finish_reason', [('', 'stop'), ('WAIT', 'stop'), ('TRANS:', 'stop'), ('partial', 'length'), (None, 'stop')])
def test_cpu_translation_rejects_incomplete_results(app, monkeypatch, content, finish_reason):
    from services.confucius import translate
    stub_completion(monkeypatch, content, finish_reason)
    with app.app_context(), pytest.raises(RuntimeError):
        translate('你好。')


def test_cpu_rejects_streaming_latency_modes(app, monkeypatch):
    from services.confucius import translate
    monkeypatch.setattr('services.confucius.requests.post', lambda *a, **kw: pytest.fail('network used'))
    with app.app_context(), pytest.raises(ValueError, match='native'):
        translate('你好。', latency_mode='low')


@pytest.mark.parametrize('language', ['auto', 'zh', 'en'])
def test_cpu_asr_encodes_normalized_wav(app, monkeypatch, tmp_path, language):
    from services.confucius import transcribe
    path = tmp_path / 'audio.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * 1600)
    calls = stub_completion(monkeypatch, 'language Chinese<asr_text>你好。')
    with app.app_context():
        result = transcribe(str(path), language=language)
    assert calls[0][0] == 'http://127.0.0.1:8273/v1/chat/completions'
    payload = calls[0][1]['json']
    encoded = payload['messages'][1]['content'][0]['input_audio']['data']
    with wave.open(io.BytesIO(base64.b64decode(encoded)), 'rb') as wav:
        assert wav.getnchannels() == 1 and wav.getframerate() == 16000
        assert wav.getsampwidth() == 2
    assert result['text'] == '你好。'
    assert result['increments'] == [{'text': '你好。', 'reset': True}]
    assert result['backend'] == 'llama-cpu'


def test_cpu_configuration_needs_no_websocket_secret(app):
    from services.confucius import service_configuration
    with app.app_context():
        assert service_configuration('confucius-r2t2') == ('http://127.0.0.1:8273/v1', None)
        app.config['CONFUCIUS_R2T2_BACKEND'] = 'invalid'
        assert 'BACKEND' in service_configuration('confucius-r2t2')[1]
        app.config['CONFUCIUS_R2T2_BACKEND'] = 'llama-cpu'
        app.config['CONFUCIUS_R2T2_CPU_URL'] = 'file:///model.gguf'
        assert 'CPU_URL' in service_configuration('confucius-r2t2')[1]


def test_cpu_refuses_external_service_and_proxies(app, monkeypatch):
    from services.confucius import service_configuration, translate
    with app.app_context():
        app.config['CONFUCIUS_T3PO_CPU_URL'] = 'https://remote-model.example'
        assert 'loopback' in service_configuration('confucius-t3po')[1]
        app.config['CONFUCIUS_T3PO_CPU_URL'] = 'http://127.0.0.1:8010'
        def post(session, *args, **kwargs):
            assert session.trust_env is False
            assert kwargs['allow_redirects'] is False
            assert kwargs['timeout'] == (10, 900)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                'choices': [{'message': {'content': 'Hello.'}, 'finish_reason': 'stop'}]})
        monkeypatch.setattr('requests.Session.post', post)
        monkeypatch.setenv('HTTP_PROXY', 'http://remote-proxy.example:1234')
        assert translate('你好。')['text'] == 'Hello.'


def test_cpu_http_errors_are_wrapped(app, monkeypatch):
    import requests
    from services.confucius import translate
    def post(*args, **kwargs):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr('services.confucius.requests.Session.post', lambda self, *args, **kwargs: post(*args, **kwargs))
    with app.app_context(), pytest.raises(RuntimeError, match='CPU'):
        translate('你好。')


def test_cpu_timeout_reports_specific_recovery(app, monkeypatch):
    import requests
    from services.confucius import translate
    def timeout(*args, **kwargs):
        raise requests.ReadTimeout('slow CPU')
    monkeypatch.setattr(requests.Session, 'post', timeout)
    with app.app_context(), pytest.raises(RuntimeError, match='CONFUCIUS_CPU_TIMEOUT_SECONDS'):
        translate('你好。')


@pytest.mark.parametrize('initial', ['missing', 'loading', 'ready'])
def test_cpu_runtime_starts_once_and_reuses_ready_server(app, monkeypatch, initial):
    import requests
    from services import confucius_cpu_runtime as runtime
    app.config['CONFUCIUS_CPU_AUTO_START'] = True
    statuses = {'missing': [None, 503, 200, 200], 'loading': [503, 200, 200],
                'ready': [200, 200]}[initial]
    def health(session, *args, **kwargs):
        assert not session.trust_env and not kwargs['allow_redirects']
        status = statuses.pop(0)
        if status is None:
            raise requests.ConnectionError('connection refused')
        return SimpleNamespace(status_code=status)
    starts = []
    def start(prefix, port):
        starts.append((prefix, port))
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(requests.Session, 'get', health)
    monkeypatch.setattr(runtime, '_start_cpu_service', start)
    monkeypatch.setattr(runtime, '_processes', {})
    monkeypatch.setattr(runtime.time, 'sleep', lambda _: None)
    with app.app_context():
        runtime.ensure_cpu_service('http://127.0.0.1:8010/v1', 'CONFUCIUS_T3PO')
        runtime.ensure_cpu_service('http://127.0.0.1:8010/v1', 'CONFUCIUS_T3PO')
    assert starts == ([('CONFUCIUS_T3PO', 8010)] if initial == 'missing' else [])


def test_cpu_runtime_startup_timeout_keeps_loading_server(app, monkeypatch):
    import requests
    from services import confucius_cpu_runtime as runtime
    app.config.update(CONFUCIUS_CPU_AUTO_START=True, CONFUCIUS_CPU_STARTUP_TIMEOUT_SECONDS=0)
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **kw: SimpleNamespace(status_code=503))
    monkeypatch.setattr(runtime, '_start_cpu_service', lambda *a: pytest.fail('duplicate server'))
    with app.app_context(), pytest.raises(RuntimeError, match='仍未加载完成'):
        runtime.ensure_cpu_service('http://127.0.0.1:8010', 'CONFUCIUS_T3PO')


def test_cpu_runtime_never_downloads_missing_assets(app, tmp_path):
    from services.confucius_cpu_runtime import _start_cpu_service
    app.config['BASE_DIR'] = str(tmp_path)
    with app.app_context(), pytest.raises(RuntimeError, match='运行时缺失'):
        _start_cpu_service('CONFUCIUS_T3PO', 8010)


def test_cpu_routes_and_readiness(scenario_api_client, monkeypatch):
    from extensions import db
    from models import AiModel
    client, headers, _ = scenario_api_client
    client.application.config.update(CONFUCIUS_T3PO_BACKEND='llama-cpu',
                                     CONFUCIUS_T3PO_CPU_URL='http://127.0.0.1:8010')
    with client.application.app_context():
        model = AiModel(model_key='confucius4-t3po', model_name='T3PO CPU',
                        task='translation', library='confucius-t3po', status='0')
        db.session.add(model)
        db.session.commit()
        mid = model.id
        from services.model_scenario_readiness import scenario_with_readiness
        from services.model_scenarios import get_scenario
        ready = scenario_with_readiness(get_scenario('confucius4-t3po'))
        assert ready['apiReady']
        assert ready['inferenceBackend'] == 'llama-cpu'
        assert ready['supportedLatencyModes'] == ['native']
    calls = stub_completion(monkeypatch, 'Hello.')
    response = client.post(f'/api/ai/model/{mid}/generate-text', headers=headers,
                           json={'text': '你好。'})
    assert response.status_code == 200
    assert response.get_json()['data']['backend'] == 'llama-cpu'
    response = client.post('/api/ai/model-scenarios/confucius4-t3po/infer', headers=headers,
                           data={'text': '你好。', 'direction': 'zh2en'})
    assert response.status_code == 200
    assert response.get_json()['data']['result']['text'] == 'Hello.'
    assert len(calls) == 2


@pytest.mark.parametrize('backend', ['official', 'llama-cpu'])
def test_model_options_include_service_models_after_first_page(scenario_api_client, backend):
    from extensions import db
    from models import AiModel
    client, headers, _ = scenario_api_client
    client.application.config.update(CONFUCIUS_R2T2_BACKEND=backend,
                                     CONFUCIUS_T3PO_BACKEND=backend)
    with client.application.app_context():
        db.session.add_all([
            AiModel(model_key=f'local-{index}', model_name=f'Local {index}',
                    library='ultralytics', task='object-detection',
                    file_path=f'models/{index}.pt', status='0')
            for index in range(105)
        ])
        db.session.flush()
        db.session.add_all([
            AiModel(model_key='confucius4-r2t2', model_name='R2T2', library='confucius-r2t2',
                    task='automatic-speech-recognition', status='0'),
            AiModel(model_key='confucius4-t3po', model_name='T3PO', library='confucius-t3po',
                    task='translation', file_path='', status='0'),
            AiModel(model_key='missing-asr', model_name='Missing ASR', library='transformers',
                    task='automatic-speech-recognition', status='0'),
            AiModel(model_key='disabled-service', model_name='Disabled ASR', library='confucius-r2t2',
                    task='automatic-speech-recognition', status='1'),
        ])
        db.session.commit()
    assert client.get('/api/ai/model/options').status_code == 401
    first_page = client.get('/api/ai/model?pageSize=100', headers=headers).get_json()['data']['rows']
    assert not any(row['modelKey'].startswith('confucius4-') for row in first_page)
    response = client.get('/api/ai/model/options', headers=headers)
    assert response.status_code == 200
    rows = response.get_json()['data']
    assert len(rows) == 107
    keys = {row['modelKey'] for row in rows}
    assert {'confucius4-r2t2', 'confucius4-t3po'} <= keys
    assert not {'missing-asr', 'disabled-service'} & keys
    for task, key in [('automatic-speech-recognition', 'confucius4-r2t2'),
                      ('translation', 'confucius4-t3po')]:
        options = client.get('/api/ai/model/options', query_string={'task': task},
                             headers=headers).get_json()['data']
        assert [row['modelKey'] for row in options] == [key]
        assert options[0]['inferenceBackend'] == backend


def test_launcher_forces_both_decoders_and_projector_to_cpu(tmp_path):
    from scripts.confucius_cpu_server import MODELS, server_command
    for model, (_, _, filename, projector, _) in MODELS.items():
        (tmp_path / filename).write_bytes(b'GGUFfake')
        if projector:
            (tmp_path / projector).write_bytes(b'GGUFfake')
        command = server_command('llama-server', model, tmp_path)
        assert command[command.index('-ngl') + 1] == '0'
        assert command[command.index('--host') + 1] == '127.0.0.1'
        assert ('--no-mmproj-offload' in command) == (model == 'r2t2')
        assert '--offline' in command
        assert command[command.index('--device') + 1] == 'none'


def test_cpu_asr_readiness_does_not_require_websockets(app):
    from services.model_scenario_contract import evaluate_scenario_contract
    from services.model_scenarios import get_scenario
    modules = []
    def probe(module):
        modules.append(module)
        return module != 'websockets'
    with app.app_context():
        result = evaluate_scenario_contract(get_scenario('confucius4-r2t2'),
            dict(task='automatic-speech-recognition', library='confucius-r2t2', status='0'),
            None, runtime_probe=probe)
    assert result.api_ready
    assert modules == ['requests', 'imageio_ffmpeg']


def test_cpu_asr_runs_without_websockets_package(app, monkeypatch, tmp_path):
    import builtins
    from services.confucius import transcribe
    original_import = builtins.__import__
    def without_websockets(name, *args, **kwargs):
        if name.startswith('websockets'):
            raise ImportError('websockets is not installed in this offline CPU environment')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_websockets)
    stub_completion(monkeypatch, 'language Chinese<asr_text>你好。')
    audio_path = tmp_path / 'offline.wav'
    with wave.open(str(audio_path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 1600)
    with app.app_context():
        assert transcribe(str(audio_path))['text'] == '你好。'


def test_cpu_adapter_roundtrip_over_http(app, tmp_path):
    import threading
    from flask import request
    from werkzeug.serving import make_server
    from services.confucius import transcribe, translate
    upstream = Flask('cpu-test-server')
    received = []
    @upstream.post('/v1/chat/completions')
    def completion():
        assert request.headers['Authorization'] == 'Bearer cpu-test-key'
        received.append(request.json)
        content = 'language English<asr_text>Hello.' if request.json['model'].endswith('R2T2') else '你好。'
        return {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}
    server = make_server('127.0.0.1', 0, upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f'http://127.0.0.1:{server.server_port}'
    app.config.update(CONFUCIUS_R2T2_CPU_URL=address, CONFUCIUS_T3PO_CPU_URL=address,
                      CONFUCIUS_R2T2_CPU_API_KEY='cpu-test-key',
                      CONFUCIUS_T3PO_CPU_API_KEY='cpu-test-key')
    path = tmp_path / 'http-audio.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 1600)
    try:
        with app.app_context():
            assert transcribe(str(path), language='en')['text'] == 'Hello.'
            assert translate('Hello.', direction='en2zh')['text'] == '你好。'
        assert len(received) == 2
        assert received[0]['messages'][-1]['content'] == 'language English<asr_text>'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
