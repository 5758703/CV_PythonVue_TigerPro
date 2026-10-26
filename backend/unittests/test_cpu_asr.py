import io
import tarfile
from pathlib import Path

import pytest
from unittests.test_moss_music import music_app

EXPECTED = {
    'paraformer-zh', 'streaming-zipformer-zh-int8', 'faster-whisper-small-int8',
    'parakeet-tdt-0p6b-v3-int8', 'moonshine-tiny-streaming',
    'moonshine-small-streaming', 'moonshine-medium-streaming', 'qwen3-asr-0p6b-int8',
}


def test_catalog_covers_all_requested_families_and_published_moonshine_sizes():
    from services.cpu_asr import CPU_ASR_MODELS
    assert set(CPU_ASR_MODELS) == EXPECTED
    assert not any('base-streaming' in key for key in CPU_ASR_MODELS)
    assert CPU_ASR_MODELS['paraformer-zh']['library'] == 'funasr'


def test_seed_is_idempotent_and_all_models_appear_without_weights(music_app):
    from services.cpu_asr import seed_cpu_asr_models
    from extensions import db
    from models import AiModel
    from routes.ai_model import list_model_options
    with music_app.app_context():
        assert seed_cpu_asr_models()
        assert not seed_cpu_asr_models()
        assert AiModel.query.count() == len(EXPECTED)
        with music_app.test_request_context('/?task=automatic-speech-recognition'):
            rows = list_model_options.__wrapped__().get_json()['data']
        assert {row['modelKey'] for row in rows} == EXPECTED
        assert all(row['asrCpu'] and row['runtimeReady'] is False for row in rows)
        model = AiModel.query.filter_by(model_key='paraformer-zh').one()
        model.status = '1'
        db.session.commit()
        seed_cpu_asr_models()
        assert model.status == '1'  # User-disabled models stay disabled.
        with music_app.test_request_context('/?task=automatic-speech-recognition'):
            rows = list_model_options.__wrapped__().get_json()['data']
        assert 'paraformer-zh' not in {r['modelKey'] for r in rows}


def test_complete_local_assets_and_dependencies_are_both_required(music_app, tmp_path):
    from services.cpu_asr import runtime_status, CPU_ASR_MODELS
    key = 'qwen3-asr-0p6b-int8'
    for name in CPU_ASR_MODELS[key]['files']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    with music_app.app_context():
        result = runtime_status(key, tmp_path, dependency_probe=lambda _: True)
        assert result['runtimeReady'] is True
        result = runtime_status(key, tmp_path, dependency_probe=lambda _: False)
        assert result['runtimeReady'] is False and 'sherpa' in result['runtimeMessage']
        (tmp_path / 'tokenizer/vocab.json').unlink()
        result = runtime_status(key, tmp_path, dependency_probe=lambda _: True)
        assert result['runtimeReady'] is False and 'vocab.json' in result['runtimeMessage']


def test_existing_paraformer_binding_is_preserved(music_app):
    from extensions import db
    from models import AiModel
    from services.cpu_asr import seed_cpu_asr_models
    with music_app.app_context():
        db.session.add(AiModel(model_key='paraformer-zh', model_name='My Paraformer',
                              library='funasr', task='automatic-speech-recognition',
                              file_path='models/custom-paraformer', status='1'))
        db.session.commit()
        seed_cpu_asr_models()
        model = AiModel.query.filter_by(model_key='paraformer-zh').one()
        assert model.file_path == 'models/custom-paraformer'
        assert model.model_name == 'My Paraformer' and model.status == '1'


def test_tar_traversal_is_rejected_before_writing(tmp_path):
    from services.cpu_asr import _extract_archive
    archive = tmp_path / 'bad.tar.bz2'
    with tarfile.open(archive, 'w:bz2') as tar:
        item = tarfile.TarInfo('model/../../escape.txt')
        item.size = 3
        tar.addfile(item, io.BytesIO(b'bad'))
    with pytest.raises(ValueError):
        _extract_archive(archive, tmp_path / 'out', ['encoder.int8.onnx'])
    assert not (tmp_path / 'escape.txt').exists()


def test_transcribe_route_uses_selected_cpu_engine(music_app, tmp_path, monkeypatch):
    from extensions import db
    from models import AiModel
    from routes.ai_model import transcribe_route
    from services import cpu_asr
    with music_app.app_context():
        cpu_asr.seed_cpu_asr_models()
        mid = AiModel.query.filter_by(model_key='faster-whisper-small-int8').one().id
    music_app.config.update(AUDIO_FOLDER=str(tmp_path / 'audio'), AUDIO_ALLOWED_EXT={'.wav'})
    monkeypatch.setattr(cpu_asr, 'runtime_status', lambda *a, **k: {'runtimeReady': True})
    calls = []
    def transcribe(key, audio_path, **kw):
        calls.append((key, kw))
        assert Path(audio_path).is_file()
        return {'text': 'hello', 'segments': [], 'timestampsAvailable': False}
    monkeypatch.setattr(cpu_asr, 'transcribe', transcribe)
    with music_app.test_request_context('/', method='POST', data={
        'file': (io.BytesIO(b'RIFF'), 'sample.wav'), 'language': 'en',
    }):
        response = transcribe_route.__wrapped__(mid)
    assert response.get_json()['data']['text'] == 'hello'
    assert calls[0][0] == 'faster-whisper-small-int8' and calls[0][1]['language'] == 'en'
    assert not list((tmp_path / 'audio').iterdir())


def test_corrupt_moonshine_files_are_not_ready(music_app, tmp_path):
    from services.cpu_asr import CPU_ASR_MODELS, runtime_status
    key = 'moonshine-tiny-streaming'
    for name in CPU_ASR_MODELS[key]['files']:
        (tmp_path / name).write_bytes(b'x')
    with music_app.app_context():
        assert not runtime_status(key, tmp_path, dependency_probe=lambda _: True)['runtimeReady']


def test_nonempty_but_corrupt_moonshine_files_still_invoke_verified_downloader(music_app, tmp_path, monkeypatch):
    from services import cpu_asr, moonshine_assets
    key = 'moonshine-tiny-streaming'
    for name in cpu_asr.CPU_ASR_MODELS[key]['files']:
        (tmp_path / name).write_bytes(b'x')
    calls = []
    monkeypatch.setattr(moonshine_assets, 'download_model', lambda arch, folder: calls.append(arch) or 123)
    monkeypatch.setattr(cpu_asr.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 20 * 1024**3})())
    with music_app.app_context():
        assert cpu_asr.download_model(key, tmp_path) == 123
    assert calls == ['tiny-streaming']


def test_explicit_paraformer_download_verifies_existing_nonempty_weights(tmp_path, monkeypatch):
    from services import cpu_asr, cpu_asr_hf_assets
    key = 'paraformer-zh'
    for name in cpu_asr.CPU_ASR_MODELS[key]['files']:
        (tmp_path / name).write_bytes(b'corrupt')
    calls = []
    monkeypatch.setattr(cpu_asr_hf_assets, 'download_hf_files',
                        lambda repo, folder, files, **kw: calls.append(repo) or 123)
    assert cpu_asr.download_model(key, tmp_path) == 123
    assert calls == ['funasr/paraformer-zh']


def test_managed_download_rejects_root_link_outside_model_folder(music_app, tmp_path, monkeypatch):
    import requests
    from services import cpu_asr
    key = 'streaming-zipformer-zh-int8'
    root = Path(music_app.config['MODEL_FOLDER'])
    outside = tmp_path / 'external'
    target = root / key
    original_resolve = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda p, *a, **kw:
                        outside if p == target else original_resolve(p, *a, **kw))
    monkeypatch.setattr(requests, 'get', lambda *a, **k: pytest.fail('unsafe target reached network'))
    with music_app.app_context(), pytest.raises(ValueError, match='越界'):
        cpu_asr.download_model(key, target)


def test_missing_custom_binding_does_not_fall_back_to_canonical_weights(music_app, tmp_path, monkeypatch):
    from services import cpu_asr
    from extensions import db
    from models import AiModel
    from routes.ai_model import transcribe_route
    key = 'faster-whisper-small-int8'
    folder = Path(music_app.config['MODEL_FOLDER']) / key
    folder.mkdir(parents=True)
    for name in cpu_asr.CPU_ASR_MODELS[key]['files']:
        (folder / name).write_bytes(b'fixture')
    music_app.config['UPLOAD_FOLDER'] = str(Path(music_app.config['MODEL_FOLDER']).parent)
    monkeypatch.setattr(cpu_asr, '_has_module', lambda _: True)
    with music_app.app_context():
        db.session.add(AiModel(model_name='Custom', model_key=key, library='faster-whisper', status='0',
                              task='automatic-speech-recognition', file_path='models/missing-custom'))
        db.session.commit()
        model = AiModel.query.filter_by(model_key=key).one()
        assert not model.to_dict()['runtimeReady']
        with music_app.test_request_context('/', method='POST'):
            response, status = transcribe_route.__wrapped__(model.id)
        assert status == 400 and '绑定' in response.get_json()['message']


def test_paraformer_prepares_bundled_ffmpeg_without_system_install(tmp_path, monkeypatch):
    from services import cpu_asr
    import imageio_ffmpeg
    source = tmp_path / 'bundled-ffmpeg.exe'
    source.write_bytes(b'existing bundled binary')
    monkeypatch.setattr(cpu_asr, 'BACKEND', tmp_path)
    monkeypatch.setattr(imageio_ffmpeg, 'get_ffmpeg_exe', lambda: str(source))
    monkeypatch.setenv('PATH', 'original-path')
    cpu_asr._ensure_funasr_ffmpeg()
    target = tmp_path / 'runtime' / 'cpu-asr-bin' / ('ffmpeg.exe' if cpu_asr.os.name == 'nt' else 'ffmpeg')
    assert target.read_bytes() == source.read_bytes()
    assert cpu_asr.os.environ['PATH'].split(cpu_asr.os.pathsep)[0] == str(target.parent)
    cpu_asr._ensure_funasr_ffmpeg()
    assert cpu_asr.os.environ['PATH'].split(cpu_asr.os.pathsep).count(str(target.parent)) == 1


def test_named_model_check_does_not_register_or_require_database(monkeypatch, capsys):
    from services import cpu_asr
    from scripts import prepare_cpu_asr
    monkeypatch.setattr(cpu_asr, 'seed_cpu_asr_models', lambda: pytest.fail('read-only check must not register'))
    monkeypatch.setattr(cpu_asr, 'runtime_status', lambda key: {'runtimeReady': False})
    monkeypatch.setattr('sys.argv', ['prepare_cpu_asr.py', '--model', 'faster-whisper-small-int8', '--check'])
    prepare_cpu_asr.main()
    assert 'faster-whisper-small-int8' in capsys.readouterr().out


def test_unknown_cpu_model_key_is_rejected_instead_of_using_funasr(music_app):
    from extensions import db
    from models import AiModel
    from routes.ai_model import transcribe_route
    with music_app.app_context():
        row=AiModel(model_name='custom',model_key='unknown-cpu-asr',library='faster-whisper',
                    task='automatic-speech-recognition',status='0')
        db.session.add(row);db.session.commit()
        with music_app.test_request_context('/',method='POST'):
            response,status=transcribe_route.__wrapped__(row.id)
        assert status==400 and '登记' in response.get_json()['message']


def test_optional_runtime_directory_is_specific_to_python_abi():
    import sys
    import sysconfig
    from services.cpu_asr import EXTRA_PACKAGES
    assert EXTRA_PACKAGES.name == f'cpu-asr-python-{sys.implementation.cache_tag}-{sysconfig.get_platform()}'


def test_new_native_engines_are_dispatched_to_isolated_worker(music_app, tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from services import cpu_asr
    calls = []
    def isolated(*args, **kwargs):
        calls.append((args, kwargs))
        return {'text': 'isolated result', 'segments': [], 'timestampsAvailable': False}
    monkeypatch.setitem(sys.modules, 'services.cpu_asr_worker_client',
                        SimpleNamespace(transcribe_isolated=isolated))
    monkeypatch.setattr(cpu_asr, 'runtime_status', lambda *a, **k: {'runtimeReady': True})
    music_app.config.update(CPU_ASR_THREADS=2, CPU_ASR_TIMEOUT_SECONDS=90)
    with music_app.app_context():
        result = cpu_asr.transcribe('moonshine-small-streaming', tmp_path / 'audio.wav',
                                    model_dir=tmp_path, language='en')
    assert result['text'] == 'isolated result'
    assert result['modelKey'] == 'moonshine-small-streaming'
    assert calls == [(('moonshine', str(tmp_path), str(tmp_path / 'audio.wav')),
                      {'threads': 2, 'language': 'en', 'model_arch': 'small-streaming', 'timeout': 90})]
    with music_app.app_context():
        cpu_asr.transcribe('moonshine-small-streaming', tmp_path / 'audio.wav', model_dir=tmp_path)
    assert calls[-1][1]['language'] == 'en'


@pytest.mark.parametrize('version,av_version', [((3, 10), '16.1.0'), ((3, 11), '16.1.0'),
                                               ((3, 12), '19.0.2'), ((3, 13), '19.0.2')])
def test_cpu_runtime_installer_selects_pyav_compatible_with_backend_python(version, av_version):
    from scripts.prepare_cpu_asr import runtime_packages
    assert f'av=={av_version}' in runtime_packages(version)
    assert 'faster-whisper==1.2.1' in runtime_packages(version)


def test_refresh_discovers_optional_runtime_created_after_backend_import(tmp_path, monkeypatch):
    import sys
    from services import cpu_asr
    target = tmp_path / 'runtime-created-later'
    module = 'cpu_asr_late_dependency_fixture'
    monkeypatch.setattr(cpu_asr, 'EXTRA_PACKAGES', target)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    assert not cpu_asr._has_module(module)
    target.mkdir()
    (target / f'{module}.py').write_text('READY = True\n')
    assert cpu_asr._has_module(module)


@pytest.mark.parametrize('key,expected_hint', [
    ('parakeet-tdt-0p6b-v3-int8', '不支持中文'),
    ('moonshine-tiny-streaming', '英文'),
    ('faster-whisper-small-int8', '音量'),
])
def test_empty_transcript_reports_model_scope_instead_of_silent_success(key, expected_hint, tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from services import cpu_asr
    monkeypatch.setitem(sys.modules, 'services.cpu_asr_worker_client', SimpleNamespace(
        transcribe_isolated=lambda *a, **k: {'text': '  ', 'segments': [], 'timestampsAvailable': False}))
    monkeypatch.setattr(cpu_asr, 'runtime_status', lambda *a, **k: {'runtimeReady': True})
    result = cpu_asr.transcribe(key, tmp_path / 'audio.wav', model_dir=tmp_path)
    assert result['recognitionStatus'] == 'empty'
    assert '未识别到文字' in result['recognitionMessage']
    assert expected_hint in result['recognitionMessage']
    assert result['text'] == '' and result['segments'] == []
