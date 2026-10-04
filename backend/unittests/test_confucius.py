import json
import asyncio
import threading
import wave
from types import SimpleNamespace

import pytest
from flask import Flask
from unittests.test_model_scenario_api import scenario_api_client
from unittests.test_openapi_model_scenarios import openapi_app, _signed_headers


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(CONFUCIUS_T3PO_URL='http://localhost:8000',
                      CONFUCIUS_R2T2_WS_URL='ws://localhost:8272/asr_stream_api_v1',
                      CONFUCIUS_R2T2_SECRET_KEY='test-secret')
    return app


def test_translation_flushes_and_preserves_increments(app, monkeypatch):
    from services import confucius
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'session_id': 'abc', 'events': [
                {'type': 'wait'}, {'type': 'translation', 'text': 'Hello '},
                {'type': 'translation', 'text': 'world.'}]})
    monkeypatch.setattr(confucius.requests, 'post', post)
    with app.app_context():
        result = confucius.translate('你好世界。', direction='zh2en', latency_mode='low')
    assert result['text'] == 'Hello world.'
    assert calls[0][0].endswith('/api/v1/translate')
    assert calls[0][1]['json'] == {
        'text': '你好世界。', 'direction': 'zh2en', 'latency_mode': 'low', 'end': True}


def test_unconfigured_service_and_invalid_direction_do_not_send(app, monkeypatch):
    from services import confucius
    monkeypatch.setattr(confucius.requests, 'post', lambda *a, **k: pytest.fail('network used'))
    with app.app_context():
        with pytest.raises(ValueError):
            confucius.translate('hi', direction='invalid')
        app.config['CONFUCIUS_T3PO_URL'] = ''
        with pytest.raises(ValueError, match='CONFUCIUS_T3PO_URL'):
            confucius.translate('hi')


def test_asr_protocol_commits_increments_and_rejects_errors():
    from services.confucius import parse_asr_message
    assert parse_asr_message(json.dumps({'status': 'connected', 'msg': ''})) is None
    assert parse_asr_message(json.dumps({'status': 'success', 'msg': {
        'text': '你好', 'reset': False}})) == {'text': '你好', 'reset': False}
    with pytest.raises(RuntimeError, match='R2T2'):
        parse_asr_message(json.dumps({'status': 'error', 'msg': 'bad secret'}))


def test_remote_contract_requires_configuration_and_no_local_weights(app):
    from services.model_scenario_contract import evaluate_scenario_contract
    from services.model_scenarios import get_scenario
    model = dict(task='translation', library='confucius-t3po', status='0')
    with app.app_context():
        scenario = get_scenario('confucius4-t3po')
        assert scenario is not None
        result = evaluate_scenario_contract(scenario, model, None, runtime_probe=lambda _: True)
        assert result.api_ready
        assert not result.weights_present
        app.config['CONFUCIUS_T3PO_URL'] = ''
        result = evaluate_scenario_contract(scenario, model, None, runtime_probe=lambda _: True)
        assert not result.api_ready
        assert 'CONFUCIUS_T3PO_URL' in result.reason


def test_audio_conversion_and_websocket_exchange(app, tmp_path):
    from services.confucius import transcribe
    from websockets.sync.server import serve
    received = []
    def handler(socket):
        received.append(json.loads(socket.recv()))
        socket.send(json.dumps({'status': 'connected', 'msg': ''}))
        while True:
            data = socket.recv()
            received.append(data)
            if isinstance(data, str):
                assert data == 'YOUDAO_ONETIME_ASR_STREAM_EOS'
                socket.send(json.dumps({'status': 'success', 'msg': {'text': '好', 'reset': True}}))
                return
            socket.send(json.dumps({'status': 'success', 'msg': {'text': '你', 'reset': False}}))

    audio_path = tmp_path / 'stereo-8k.wav'
    with wave.open(str(audio_path), 'wb') as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * 800 * 2)
    with serve(handler, '127.0.0.1', 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        app.config['CONFUCIUS_R2T2_WS_URL'] = f'ws://127.0.0.1:{server.socket.getsockname()[1]}/asr_stream_api_v1'
        try:
            with app.app_context():
                result = transcribe(str(audio_path), language='zh')
            assert result['text'] == '你好'
            assert result['increments'][-1]['reset']
            assert received[0]['sample_rate'] == 16000
            assert received[0]['channels'] == 1
            assert received[0]['language'] == 'Chinese'
            assert received[0]['secret_key'] == 'test-secret'
            assert len(b''.join(x for x in received if isinstance(x, bytes))) == 3200
        finally:
            server.shutdown()
            thread.join(timeout=3)


def test_asr_rejects_premature_normal_close():
    from services.confucius import _transcribe_pcm
    from websockets.sync.server import serve
    def handler(socket):
        socket.recv()
        socket.send(json.dumps({'status': 'connected'}))
        while isinstance(socket.recv(), bytes):
            pass
        # No final reset: even a normal close must not return partial success.
    with serve(handler, '127.0.0.1', 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with pytest.raises(RuntimeError, match='提前结束'):
                asyncio.run(_transcribe_pcm(f'ws://127.0.0.1:{server.socket.getsockname()[1]}',
                                           'key', b'\0\0' * 160, 'Chinese', 3))
        finally:
            server.shutdown()
            thread.join(timeout=3)


def test_management_and_scenario_translation_without_local_weights(scenario_api_client, monkeypatch):
    from extensions import db
    from models import AiModel
    from services import confucius
    client, headers, _ = scenario_api_client
    client.application.config['CONFUCIUS_T3PO_URL'] = 'http://localhost:8000'
    with client.application.app_context():
        model = AiModel(model_key='confucius4-t3po', model_name='T3PO', task='translation',
                        library='confucius-t3po', status='0')
        db.session.add(model)
        db.session.commit()
        mid = model.id
    calls = []
    def translate(text, **options):
        calls.append((text, options))
        return {'text': '你好', 'events': []}
    monkeypatch.setattr(confucius, 'translate', translate)
    assert client.post(f'/api/ai/model/{mid}/generate-text', json={'text': 'Hello'}).status_code == 401
    response = client.post(f'/api/ai/model/{mid}/generate-text', headers=headers,
                           json={'text': 'Hello', 'direction': 'en2zh', 'latencyMode': 'high'})
    assert response.status_code == 200
    assert response.get_json()['data']['text'] == '你好'
    response = client.post('/api/ai/model-scenarios/confucius4-t3po/infer', headers=headers,
                           data={'text': 'Hello', 'direction': 'en2zh', 'latencyMode': 'high'})
    assert response.status_code == 200
    assert response.get_json()['data']['result']['text'] == '你好'
    assert calls == [('Hello', {'direction': 'en2zh', 'latency_mode': 'high'})] * 2
    with client.application.app_context():
        model = db.session.get(AiModel, mid)
        model.status = '1'
        db.session.commit()
    assert client.post(f'/api/ai/model/{mid}/generate-text', headers=headers,
                       json={'text': 'Hello'}).status_code == 400


def test_openapi_translation_preserves_parameters_and_requires_scope(openapi_app, monkeypatch):
    from extensions import db
    from models import AiModel
    from services import confucius
    app, reader, runner = openapi_app
    app.config['CONFUCIUS_T3PO_URL'] = 'http://localhost:8000'
    with app.app_context():
        db.session.add(AiModel(model_key='confucius4-t3po', model_name='T3PO', task='translation',
                              library='confucius-t3po', status='0'))
        db.session.commit()
    calls = []
    def translate(text, **kwargs):
        calls.append((text, kwargs))
        return {'text': 'Hello', 'events': []}
    monkeypatch.setattr(confucius, 'translate', translate)
    path = '/openapi/v1/model-scenarios/confucius4-t3po/infer'
    client = app.test_client()
    assert client.post(path, headers=reader, data={'text': '你好'}).status_code == 403
    data = {'text': '你好', 'direction': 'zh2en', 'latencyMode': 'low'}
    response = client.post(path, headers=_signed_headers(runner, 'POST', path, data),
                           data=data, content_type='multipart/form-data')
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['data']['result']['text'] == 'Hello'
    assert calls == [('你好', {'direction': 'zh2en', 'latency_mode': 'low'})]
    tampered = {**data, 'direction': 'en2zh'}
    response = client.post(path, headers=_signed_headers(runner, 'POST', path, data),
                           data=tampered, content_type='multipart/form-data')
    assert response.status_code == 401
    assert len(calls) == 1


def test_signed_openapi_asr_accepts_language_and_cleans_file(openapi_app, monkeypatch):
    import io
    from pathlib import Path
    from extensions import db
    from models import AiModel
    from services import confucius
    app, _, runner = openapi_app
    app.config.update(CONFUCIUS_R2T2_WS_URL='ws://localhost:8272/asr_stream_api_v1',
                      CONFUCIUS_R2T2_SECRET_KEY='test')
    with app.app_context():
        db.session.add(AiModel(model_key='confucius4-r2t2', model_name='R2T2',
                              task='automatic-speech-recognition', library='confucius-r2t2', status='0'))
        db.session.commit()
    paths = []
    def transcribe(path, **options):
        assert options == {'language': 'en'}
        assert Path(path).read_bytes() == b'fake-audio'
        paths.append(Path(path))
        return {'text': 'Hello', 'increments': []}
    monkeypatch.setattr(confucius, 'transcribe', transcribe)
    path = '/openapi/v1/model-scenarios/confucius4-r2t2/infer'
    data = {'language': 'en', 'file': (io.BytesIO(b'fake-audio'), 'audio.wav')}
    response = app.test_client().post(path, headers=_signed_headers(runner, 'POST', path, data),
                                      data=data, content_type='multipart/form-data')
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['data']['result']['text'] == 'Hello'
    assert len(paths) == 1 and not paths[0].exists()


def test_asr_management_and_scenario_routes_clean_uploads(scenario_api_client, monkeypatch):
    import io
    from extensions import db
    from models import AiModel
    from services import confucius
    client, headers, folder = scenario_api_client
    client.application.config.update(CONFUCIUS_R2T2_WS_URL='ws://localhost:8272/asr_stream_api_v1',
        CONFUCIUS_R2T2_SECRET_KEY='test', AUDIO_FOLDER=str(folder / 'audio'),
        AUDIO_ALLOWED_EXT={'.wav'})
    with client.application.app_context():
        model = AiModel(model_key='confucius4-r2t2', model_name='R2T2',
                        task='automatic-speech-recognition', library='confucius-r2t2', status='0')
        db.session.add(model)
        db.session.commit()
        mid = model.id
    paths = []
    def transcribe(path, **kwargs):
        from pathlib import Path
        assert Path(path).exists()
        assert kwargs == {'language': 'en'}
        paths.append(Path(path))
        return {'text': 'Hello', 'increments': []}
    monkeypatch.setattr(confucius, 'transcribe', transcribe)
    for path in (f'/api/ai/model/{mid}/transcribe', '/api/ai/model-scenarios/confucius4-r2t2/infer'):
        response = client.post(path, headers=headers, data={
            'file': (io.BytesIO(b'fake-audio'), 'sample.wav'), 'language': 'en'})
        assert response.status_code == 200
    assert len(paths) == 2
    assert all(not path.exists() for path in paths)


def test_invalid_service_urls_are_reported_without_network(app):
    from services.confucius import service_configuration
    with app.app_context():
        for url in ('http://[', 'http://host:invalid', 'file:///tmp/model', 'http://user:pass@host'):
            app.config['CONFUCIUS_T3PO_URL'] = url
            assert service_configuration('confucius-t3po')[1]
