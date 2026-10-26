import io
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask


@pytest.fixture
def music_app(tmp_path):
    app = Flask(__name__)
    app.config.update(MODEL_FOLDER=str(tmp_path / 'models'),
                      SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      MOSS_MUSIC_EXECUTABLE=str(tmp_path / 'ace-caption.exe'),
                      MOSS_MUSIC_MAX_SECONDS=60, MOSS_MUSIC_MAX_TOKENS=256,
                      MOSS_MUSIC_THREADS=4, MOSS_MUSIC_TIMEOUT_SECONDS=30)
    from extensions import db
    from models import AiModel  # Register tables before create_all, including isolated test runs.
    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app


def _assets(app):
    from services import moss_music
    folder = Path(app.config['MODEL_FOLDER']) / moss_music.MODEL_KEY
    folder.mkdir(parents=True)
    for name in moss_music.WEIGHT_FILES:
        (folder / name).write_bytes(b'GGUF' + b'\0' * 32)
    Path(app.config['MOSS_MUSIC_EXECUTABLE']).write_bytes(b'executable')
    return folder


def _wav(path, seconds=1):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b'\0\0' * 16000 * seconds)


def test_registered_music_is_visible_without_weights(music_app):
    from extensions import db
    from models import AiModel
    from routes.ai_model import list_model_options
    with music_app.app_context():
        db.create_all()
        db.session.add(AiModel(model_key='moss-music-8b-instruct-gguf', model_name='MOSS Music',
                              task='audio-text-to-text', library='moss-music-gguf', status='0'))
        db.session.commit()
        with music_app.test_request_context('/?task=audio-text-to-text'):
            payload = list_model_options.__wrapped__().get_json()
        assert len(payload['data']) == 1
        row = payload['data'][0]
        assert row['runtimeReady'] is False
        assert 'moss-' in row['runtimeMessage']


def test_missing_audio_tower_is_reported(music_app):
    from services import moss_music
    folder = _assets(music_app)
    (folder / 'moss-aud-f16.gguf').unlink()
    with music_app.app_context():
        state = moss_music.runtime_status()
    assert not state['runtimeReady']
    assert 'moss-aud-f16.gguf' in state['runtimeMessage']


def test_cpu_command_reads_single_mode_output_and_returns_no_fake_timestamps(music_app, tmp_path, monkeypatch):
    from services import moss_music
    _assets(music_app)
    audio = tmp_path / 'input.wav'
    _wav(audio)
    calls = []
    def run(cmd, **kw):
        calls.append((cmd, kw))
        Path(cmd[cmd.index('-o') + 1]).write_text('真实歌词', encoding='utf-8')
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr(moss_music.subprocess, 'run', run)
    with music_app.app_context():
        result = moss_music.analyze(str(audio), mode='lyrics')
    cmd, kw = calls[0]
    assert kw['env']['GGML_BACKEND'] == 'CPU'
    assert kw['env']['GGML_N_THREADS'] == '4'
    assert '--encoder-window' in cmd
    assert cmd[cmd.index('--mode') + 1] == 'lyrics'
    assert result['text'] == '真实歌词'
    assert result['segments'] == [] and result['timestampsAvailable'] is False
    assert result['durationSeconds'] == 1
    assert result['rtf'] >= 0


def test_rejects_long_audio_instead_of_silently_truncating(music_app, tmp_path, monkeypatch):
    from services import moss_music
    _assets(music_app)
    audio = tmp_path / 'long.wav'
    _wav(audio, 2)
    music_app.config['MOSS_MUSIC_MAX_SECONDS'] = 1
    monkeypatch.setattr(moss_music.subprocess, 'run', lambda *a, **k: pytest.fail('must not start'))
    with music_app.app_context(), pytest.raises(ValueError, match='1'):
        moss_music.analyze(str(audio))


@pytest.mark.parametrize('failure', ['empty', 'exit', 'timeout'])
def test_runtime_failures_do_not_return_success(music_app, tmp_path, monkeypatch, failure):
    from services import moss_music
    _assets(music_app)
    audio = tmp_path / 'input.wav'
    _wav(audio)
    def run(cmd, **kw):
        if failure == 'timeout':
            raise moss_music.subprocess.TimeoutExpired(cmd, 30)
        return SimpleNamespace(returncode=1 if failure == 'exit' else 0, stderr='runtime failed')
    monkeypatch.setattr(moss_music.subprocess, 'run', run)
    with music_app.app_context(), pytest.raises(RuntimeError):
        moss_music.analyze(str(audio))


def test_download_only_required_pair(tmp_path, monkeypatch):
    from services import moss_music
    import huggingface_hub
    calls = []
    def download(**kw):
        calls.append(kw['filename'])
        path = tmp_path / kw['filename']
        path.write_bytes(b'GGUF' + b'\0' * 32)
        return str(path)
    monkeypatch.setattr(huggingface_hub, 'hf_hub_download', download)
    monkeypatch.setattr(moss_music.shutil, 'disk_usage', lambda _: SimpleNamespace(free=20 * 1024**3))
    moss_music.download_weights(str(tmp_path))
    assert calls == ['moss-lm-q8_0.gguf', 'moss-aud-f16.gguf']


def test_transcribe_route_dispatches_music_and_preserves_mode(music_app, tmp_path, monkeypatch):
    from routes.ai_model import transcribe_route
    from models import AiModel
    from services import moss_music
    _assets(music_app)
    music_app.config.update(AUDIO_FOLDER=str(tmp_path / 'audio'), AUDIO_ALLOWED_EXT={'.wav'})
    from extensions import db
    with music_app.app_context():
        model = AiModel(model_name='Music', library='moss-music-gguf', status='0', file_path=None,
                        task='audio-text-to-text')
        db.session.add(model)
        db.session.commit()
        mid = model.id
    monkeypatch.setattr('routes.ai_model._abs_model_path', lambda _: None)
    calls = []
    def analyze(path, **kw):
        assert Path(path).is_file()
        calls.append(kw)
        return {'text': '乐器分析', 'timestampsAvailable': False}
    monkeypatch.setattr(moss_music, 'analyze', analyze)
    with music_app.test_request_context('/', method='POST', data={
            'file': (io.BytesIO(b'RIFF'), 'music.wav'), 'mode': 'prose'}):
        response = transcribe_route.__wrapped__(mid)
    assert response.get_json()['data']['text'] == '乐器分析'
    assert calls[0]['mode'] == 'prose'
    assert not list((tmp_path / 'audio').iterdir())


def test_download_rejects_insufficient_disk_before_network(tmp_path, monkeypatch):
    from services import moss_music
    import huggingface_hub
    monkeypatch.setattr(moss_music.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1024))
    monkeypatch.setattr(huggingface_hub, 'hf_hub_download', lambda **_: pytest.fail('network used'))
    with pytest.raises(ValueError, match='磁盘空间不足'):
        moss_music.download_weights(tmp_path)
