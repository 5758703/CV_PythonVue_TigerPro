"""CPU adapters: SDK boundaries are faked because weights are multi-GB."""
import importlib
import sys
import wave
from enum import IntEnum
from types import SimpleNamespace as NS

import numpy as np
import pytest


def adapter():
    return importlib.import_module('services.cpu_asr_engines')


@pytest.fixture
def env(monkeypatch, tmp_path):
    module = adapter()
    module._MODEL_CACHE.clear()
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'local-audio')
    monkeypatch.setattr(module, '_decode_audio', lambda path, **kwargs: np.ones(16003, dtype=np.float32))
    yield module, tmp_path, str(audio)
    module._MODEL_CACHE.clear()


def assets(root, names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'local-model')


def test_adapter_is_available_without_loading_heavy_sdks():
    assert callable(adapter().transcribe)


@pytest.mark.parametrize('threads', [0, -1, True, 1.5, 257])
def test_invalid_thread_count_rejected_before_loading(env, threads):
    module, root, audio = env
    with pytest.raises(ValueError, match='threads'):
        module.transcribe('zipformer', str(root), audio, threads=threads)


def test_nonlocal_model_name_is_rejected(env):
    module, root, audio = env
    with pytest.raises(ValueError, match='local'):
        module.transcribe('faster-whisper', 'small', audio)


def test_incomplete_whisper_cannot_trigger_tokenizer_download(env, monkeypatch):
    module, root, audio = env
    assets(root, ['model.bin', 'config.json'])
    monkeypatch.setitem(sys.modules, 'faster_whisper', NS(WhisperModel=lambda *a, **k: pytest.fail('must validate tokenizer first')))
    with pytest.raises(ValueError, match='tokenizer.json'):
        module.transcribe('faster-whisper', str(root), audio)


def test_whisper_cpu_int8_local_only_and_real_segment_timing(env, monkeypatch):
    module, root, audio = env
    assets(root, ['model.bin', 'config.json', 'tokenizer.json', 'preprocessor_config.json'])
    calls = []
    class Whisper:
        def __init__(self, path, **kwargs):
            calls.append(kwargs)
            assert path == str(root.resolve())
        def transcribe(self, samples, **kwargs):
            assert samples.dtype == np.float32 and samples.shape == (16003,)
            assert kwargs['language'] is None
            return iter([NS(start=.25, end=.75, text=' Hello')]), NS(language='en')
    monkeypatch.setitem(sys.modules, 'faster_whisper', NS(WhisperModel=Whisper))
    result = module.transcribe('faster-whisper', str(root), audio, threads=3)
    assert result['text'] == 'Hello'
    assert result['segments'] == [{'start': .25, 'end': .75, 'text': 'Hello'}]
    assert result['timestampsAvailable'] is True
    assert result['language'] == 'en'
    assert calls == [{'device': 'cpu', 'compute_type': 'int8', 'cpu_threads': 3, 'num_workers': 1, 'local_files_only': True}]
    module.transcribe('faster-whisper', str(root), audio, threads=3)
    assert len(calls) == 1


class Offline:
    def __init__(self, result):
        self.result = result
    def create_stream(self):
        return NS(accept_waveform=self.accept, result=self.result)
    def accept(self, sample_rate, samples):
        assert sample_rate == 16000 and samples.dtype == np.float32 and samples.ndim == 1
    def decode_stream(self, stream):
        pass


def test_parakeet_tdt_cpu_dispatch_keeps_starts_out_of_subtitle_segments(env, monkeypatch):
    module, root, audio = env
    assets(root, ['encoder.int8.onnx', 'decoder.int8.onnx', 'joiner.int8.onnx', 'tokens.txt'])
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return Offline(NS(text=' Hello world', tokens=[' Hello', ' world'], timestamps=[.2, .6], lang=''))
    monkeypatch.setitem(sys.modules, 'sherpa_onnx', NS(OfflineRecognizer=NS(from_transducer=factory)))
    result = module.transcribe('parakeet', str(root), audio)
    assert calls[0]['model_type'] == 'nemo_transducer'
    assert calls[0]['provider'] == 'cpu'
    assert calls[0]['feature_dim'] == 80
    assert result['segments'] == []
    assert result['timestampsAvailable'] is False
    assert result['tokens'] == [' Hello', ' world']
    assert result['timestamps'] == [.2, .6]
    assert result['timestampKind'] == 'token-start'
    assert result['language'] is None  # no language detection is exposed by this model


def test_qwen_local_assets_and_no_fabricated_timing(env, monkeypatch):
    module, root, audio = env
    assets(root, ['conv_frontend.onnx', 'encoder.int8.onnx', 'decoder.int8.onnx', 'tokenizer/vocab.json', 'tokenizer/merges.txt', 'tokenizer/tokenizer_config.json'])
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return Offline(NS(text='你好', tokens=[], timestamps=[], lang='Chinese'))
    monkeypatch.setitem(sys.modules, 'sherpa_onnx', NS(OfflineRecognizer=NS(from_qwen3_asr=factory)))
    result = module.transcribe('qwen3', str(root), audio)
    assert calls[0]['provider'] == 'cpu' and calls[0]['feature_dim'] == 128
    assert calls[0]['max_new_tokens'] == 512 and calls[0]['max_total_len'] == 2048
    assert calls[0]['tokenizer'] == str(root / 'tokenizer')
    assert result['text'] == '你好' and result['language'] == 'zh'
    assert result['segments'] == [] and result['timestampsAvailable'] is False


def test_qwen_explicit_language_not_silently_ignored(env):
    module, root, audio = env
    with pytest.raises(ValueError, match='auto'):
        module.transcribe('qwen3', str(root), audio, language='en')


@pytest.mark.parametrize('engine,seconds', [('qwen3', 60), ('parakeet', 120), ('zipformer', 600), ('moonshine', 600), ('faster-whisper', 600)])
def test_oversize_audio_rejected_before_model_load(env, monkeypatch, engine, seconds):
    module, root, audio = env
    samples = np.broadcast_to(np.float32(0), (seconds * 16000 + 1,))
    monkeypatch.setattr(module, '_decode_audio', lambda path, **kwargs: samples)
    monkeypatch.setattr(module, '_load_model', lambda *args: pytest.fail('oversize audio must not load weights'))
    with pytest.raises(ValueError, match=str(seconds)):
        module.transcribe(engine, str(root), audio, model_arch='tiny-streaming' if engine == 'moonshine' else None)


def test_zipformer_chunks_tail_and_finished_input_are_decoded(env, monkeypatch):
    module, root, audio = env
    assets(root, ['encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt'])
    chunks, state = [], {'pending': 0, 'finished': False, 'decodes': 0}
    class Online:
        def create_stream(self):
            return NS(accept_waveform=self.accept, input_finished=lambda: state.update(finished=True))
        def accept(self, rate, samples):
            assert rate == 16000 and samples.dtype == np.float32
            chunks.append(samples.copy())
            state['pending'] += 1
        def is_ready(self, stream):
            return state['pending'] > 0
        def decode_stream(self, stream):
            state['pending'] -= 1
            state['decodes'] += 1
        def get_result_all(self, stream):
            assert state['finished'] and not state['pending']
            return NS(text='你好', tokens=[], timestamps=[])
    def factory(**kwargs):
        assert kwargs['provider'] == 'cpu' and kwargs['enable_endpoint_detection'] is False
        return Online()
    monkeypatch.setitem(sys.modules, 'sherpa_onnx', NS(OnlineRecognizer=NS(from_transducer=factory)))
    result = module.transcribe('zipformer', str(root), audio)
    assert len(chunks) > 2
    np.testing.assert_array_equal(np.concatenate(chunks[:-1]), np.ones(16003, dtype=np.float32))
    assert len(chunks[-1]) == 10560 and not chunks[-1].any()
    assert result['text'] == '你好' and result['segments'] == []


@pytest.mark.parametrize('arch,arch_value', [('tiny-streaming', 2), ('small-streaming', 4), ('medium-streaming', 5)])
def test_moonshine_stream_flushes_trailing_audio_and_preserves_line_times(env, monkeypatch, arch, arch_value):
    module, root, audio = env
    assets(root, ['adapter.ort', 'cross_kv.ort', 'decoder_kv.ort', 'encoder.ort', 'frontend.model.ort', 'frontend.weights.ort', 'streaming_config.json', 'tokenizer.bin'])
    calls, chunks = [], []
    class ModelArch(IntEnum):
        TINY_STREAMING = 2
        SMALL_STREAMING = 4
        MEDIUM_STREAMING = 5
    class Stream:
        def add_listener(self, listener): pass
        def start(self): calls.append('start')
        def add_audio(self, samples, sample_rate):
            assert sample_rate == 16000
            chunks.extend(samples)
        def stop(self):
            calls.append('stop')
            return NS(lines=[NS(text='Hello', start_time=.1, duration=.8, line_id=7, is_complete=True)])
        def close(self): calls.append('close')
    class Transcriber:
        def __init__(self, **kwargs):
            assert kwargs['model_arch'] == arch_value
            assert kwargs['options']['ort_provider'] == 'cpu'
        def create_stream(self): return Stream()
        def close(self): pass
    monkeypatch.setitem(sys.modules, 'moonshine_voice', NS(Transcriber=Transcriber, ModelArch=ModelArch))
    result = module.transcribe('moonshine', str(root), audio, model_arch=arch)
    assert len(chunks) == 16003 and calls == ['start', 'stop', 'close']
    assert result['segments'] == [{'start': .1, 'end': .9, 'text': 'Hello'}]
    assert result['language'] == 'en'


def test_moonshine_does_not_hide_sdk_stream_errors(env, monkeypatch):
    module, root, audio = env
    assets(root, ['adapter.ort', 'cross_kv.ort', 'decoder_kv.ort', 'encoder.ort', 'frontend.model.ort', 'frontend.weights.ort', 'streaming_config.json', 'tokenizer.bin'])
    class Stream:
        def add_listener(self, callback): self.callback = callback
        def start(self): pass
        def add_audio(self, samples, sample_rate):
            self.callback(NS(error=RuntimeError('native inference failed')))
        def stop(self): return NS(lines=[])
        def close(self): pass
    monkeypatch.setitem(sys.modules, 'moonshine_voice', NS(
        ModelArch=NS(TINY_STREAMING=2),
        Transcriber=lambda **kwargs: NS(create_stream=lambda: Stream())))
    with pytest.raises(RuntimeError, match='native inference failed'):
        module.transcribe('moonshine', str(root), audio, model_arch='tiny-streaming')


def test_model_switch_releases_cached_model_before_loading_replacement(env, monkeypatch):
    module, root, audio = env
    assets(root, ['encoder.int8.onnx', 'decoder.int8.onnx', 'joiner.int8.onnx', 'tokens.txt'])
    seen = []
    class Model(Offline):
        def close(self): seen.append('closed')
    def factory(**kwargs):
        if seen:
            assert seen[-1] == 'closed'
        seen.append('loaded')
        return Model(NS(text='', tokens=[], timestamps=[], lang=''))
    monkeypatch.setitem(sys.modules, 'sherpa_onnx', NS(OfflineRecognizer=NS(from_transducer=factory)))
    first = module.transcribe('parakeet', str(root), audio, threads=1)
    module.transcribe('parakeet', str(root), audio, threads=2)
    assert seen == ['loaded', 'closed', 'loaded']
    assert first['text'] == '' and first['segments'] == []


def test_moonshine_rejects_unpublished_base_streaming(env):
    module, root, audio = env
    with pytest.raises(ValueError, match='model_arch'):
        module.transcribe('moonshine', str(root), audio, model_arch='base-streaming')


def test_missing_dependency_has_actionable_error(env, monkeypatch):
    module, root, audio = env
    assets(root, ['encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt'])
    monkeypatch.setitem(sys.modules, 'sherpa_onnx', None)
    with pytest.raises(ValueError, match='sherpa-onnx'):
        module.transcribe('zipformer', str(root), audio)


def test_decode_normalizes_stereo_and_resamples_with_ffmpeg(tmp_path):
    audio = tmp_path / 'stereo.wav'
    with wave.open(str(audio), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(np.full((800, 2), 8192, dtype='<i2').tobytes())
    samples = adapter()._decode_audio(str(audio))
    assert samples.shape == (1600,) and samples.dtype == np.float32
    assert np.allclose(samples[20:-20], .25, atol=.001)


def test_ffmpeg_decode_is_bounded_before_oversize_input_rejection(tmp_path, monkeypatch):
    module = adapter()
    path = tmp_path / 'compressed-audio.mp3'
    path.write_bytes(b'input is decoded by the ffmpeg boundary stub')
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return NS(returncode=0, stdout=np.zeros(61 * 16000, dtype='<f4').tobytes(), stderr=b'')
    monkeypatch.setattr(module.subprocess, 'run', run)
    monkeypatch.setattr(module, '_load_model', lambda *args: pytest.fail('long input must not load weights'))
    with pytest.raises(ValueError, match='60 seconds'):
        module.transcribe('qwen3', str(tmp_path), str(path))
    command = commands[0]
    assert command[command.index('-t') + 1] == '61'


def test_real_ffmpeg_stops_after_maximum_plus_one_second(tmp_path):
    audio = tmp_path / 'long.wav'
    with wave.open(str(audio), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 48000)
    samples = adapter()._decode_audio(str(audio), max_seconds=1)
    assert len(samples) == 32000  # Two seconds buffered, not all three seconds.
