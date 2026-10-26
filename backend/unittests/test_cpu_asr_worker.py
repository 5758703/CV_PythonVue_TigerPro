"""Exercise the real subprocess transport without loading model weights."""
import importlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    module = importlib.import_module('services.cpu_asr_worker_client')
    module._cleanup()
    script = tmp_path / 'fake_native_worker.py'
    script.write_text('''import json,os,sys,time
PREFIX='__CPU_ASR_RESPONSE_V1__:'
for line in sys.stdin:
    request=json.loads(line)
    action=os.path.basename(request['audio_path'])
    if action=='crash': os._exit(23)
    if action=='timeout': time.sleep(20)
    print('native SDK diagnostic log',flush=True)
    if action=='invalid':
        response={'id':request['id'],'ok':False,'error':{'type':'ValueError','message':'local model assets missing'}}
    elif action=='wrong-id':
        response={'id':'wrong','ok':True,'result':{}}
    else:
        response={'id':request['id'],'ok':True,'result':{'text':'actual child result','pid':os.getpid(),'request':request,'mkl':os.environ.get('MKL_THREADING_LAYER'),'unsafe':os.environ.get('KMP_DUPLICATE_LIB_OK')}}
    print(PREFIX+json.dumps(response),flush=True)
''', encoding='utf-8')
    monkeypatch.setattr(module, '_WORKER_SCRIPT', script)
    monkeypatch.setattr(module, '_LOG_DIR', tmp_path / 'logs')
    yield module
    module._cleanup()


def infer(client, **kwargs):
    arguments = dict(engine='moonshine', model_dir='local-model', audio_path='sample.wav',
                     threads=3, language='en', model_arch='tiny-streaming', timeout=10)
    arguments.update(kwargs)
    return client.transcribe_isolated(**arguments)


def test_subprocess_returns_result_despite_sdk_logs_and_passes_options(client):
    result = infer(client)
    assert result['text'] == 'actual child result'
    assert result['request']['threads'] == 3
    assert result['request']['language'] == 'en'
    assert result['request']['model_arch'] == 'tiny-streaming'
    assert Path(result['request']['model_dir']).is_absolute()
    assert result['mkl'] == 'SEQUENTIAL' and result['unsafe'] is None


def test_same_model_reuses_process_and_allows_language_change(client):
    first = infer(client)
    second = infer(client, language='auto')
    assert first['pid'] == second['pid']
    assert first['request']['id'] != second['request']['id']


@pytest.mark.parametrize('changed', [dict(engine='zipformer'), dict(model_dir='other-model'), dict(threads=4), dict(model_arch='small-streaming')])
def test_model_switch_terminates_old_process_before_new_request(client, changed):
    first = infer(client)
    old = client._WORKER.process
    second = infer(client, **changed)
    assert first['pid'] != second['pid']
    assert old.poll() is not None


def test_native_exit_is_reported_without_killing_parent_and_next_request_recovers(client):
    with pytest.raises(RuntimeError, match='23'):
        infer(client, audio_path='crash')
    assert infer(client)['text'] == 'actual child result'


def test_deadline_terminates_worker_and_next_request_recovers(client):
    with pytest.raises(RuntimeError, match='timed out'):
        infer(client, audio_path='timeout', timeout=.2)
    assert client._WORKER is None
    assert infer(client)['text'] == 'actual child result'


def test_worker_value_error_is_actionable_and_process_stays_reusable(client):
    first = infer(client)
    with pytest.raises(ValueError, match='local model assets missing'):
        infer(client, audio_path='invalid')
    assert infer(client)['pid'] == first['pid']


def test_mismatched_response_cannot_satisfy_request(client):
    with pytest.raises(RuntimeError, match='protocol'):
        infer(client, audio_path='wrong-id')
    assert client._WORKER is None


@pytest.mark.parametrize('timeout', [0, -1, float('inf'), float('nan')])
def test_invalid_deadline_rejected_before_starting_process(client, timeout):
    with pytest.raises(ValueError, match='timeout'):
        infer(client, timeout=timeout)
    assert client._WORKER is None


def worker_module():
    path = Path(__file__).resolve().parents[1] / 'scripts/cpu_asr_worker.py'
    spec = importlib.util.spec_from_file_location('isolated_asr_worker_protocol', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_worker_protocol_dispatch_and_error_envelope():
    module = worker_module()
    request = dict(id='one', version=1, engine='qwen3', model_dir='local', audio_path='file.wav',
                   threads=2, language='auto', model_arch=None)
    calls = []
    def transcribe(*args, **kwargs):
        calls.append((args, kwargs))
        if args[2] == 'missing.wav':
            raise ValueError('audio missing')
        return {'text': '你好', 'segments': [], 'timestampsAvailable': False}
    other = dict(request, id='two', audio_path='missing.wav')
    output = io.StringIO()
    module.serve(io.StringIO(json.dumps(request)+'\n'+json.dumps(other)+'\n'), output, transcribe)
    responses = [json.loads(line.removeprefix(module.RESPONSE_PREFIX)) for line in output.getvalue().splitlines() if line.startswith(module.RESPONSE_PREFIX)]
    assert responses[0]['result']['text'] == '你好'
    assert responses[1]['error'] == {'type': 'ValueError', 'message': 'audio missing'}
    assert calls[0] == (('qwen3', 'local', 'file.wav'), {'threads': 2, 'language': 'auto', 'model_arch': None})


def test_worker_refuses_model_switch_within_process():
    module = worker_module()
    first = dict(id='a', version=1, engine='zipformer', model_dir='a', audio_path='a.wav', threads=4, language='auto', model_arch=None)
    second = dict(first, id='b', engine='faster-whisper')
    output = io.StringIO()
    module.serve(io.StringIO(json.dumps(first)+'\n'+json.dumps(second)+'\n'), output, lambda *a, **k: {'text': 'one model'})
    responses = [json.loads(line.removeprefix(module.RESPONSE_PREFIX)) for line in output.getvalue().splitlines() if line.startswith(module.RESPONSE_PREFIX)]
    assert responses[1]['ok'] is False
    assert 'model switch' in responses[1]['error']['message']
