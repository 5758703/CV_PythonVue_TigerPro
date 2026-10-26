"""Managed Moonshine downloads: all network traffic is replaced at HTTP boundary."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('arch', ['tiny-streaming', 'small-streaming', 'medium-streaming'])
def test_required_files_selects_published_streaming_layout(arch):
    from services import moonshine_assets as assets

    assert assets.required_files(arch) == (
        'adapter.ort', 'cross_kv.ort', 'decoder_kv.ort', 'encoder.ort',
        'frontend.model.ort', 'frontend.weights.ort', 'streaming_config.json',
        'tokenizer.bin',
    )


@pytest.mark.parametrize('arch', ['base-streaming', '../../tiny-streaming', '', 'unknown'])
def test_unpublished_architecture_is_rejected(arch, tmp_path):
    from services import moonshine_assets as assets

    with pytest.raises(ValueError):
        assets.download_model(arch, str(tmp_path))


@pytest.fixture
def miniature_models(monkeypatch):
    from services import moonshine_assets as assets

    # Standard CRC32C check vector, independently published as 0xe3069283.
    files = (assets.Asset('adapter.ort', 9, '4waSgw=='),
             assets.Asset('tokenizer.bin', 9, '4waSgw=='))
    monkeypatch.setattr(assets, '_MODELS', {
        'tiny-streaming': files, 'small-streaming': files, 'medium-streaming': files,
    })
    monkeypatch.setattr(assets.shutil, 'disk_usage', lambda path: SimpleNamespace(free=10**9))
    return assets


class Response:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield from self.chunks


@pytest.mark.parametrize('arch', ['tiny-streaming', 'small-streaming', 'medium-streaming'])
def test_download_selects_pinned_assets_and_skips_only_verified_files(
        miniature_models, monkeypatch, tmp_path, arch):
    assets = miniature_models
    (tmp_path / 'adapter.ort').write_bytes(b'123456789')
    (tmp_path / 'tokenizer.bin').write_bytes(b'corrupted')  # Same size, wrong CRC.
    (tmp_path / 'tokenizer.bin.part').write_bytes(b'abandoned')

    def get(url, **kwargs):
        assert url == (f'https://download.moonshine.ai/model/{arch}-en/'
                       'quantized_26_08_21/tokenizer.bin')
        assert kwargs['stream'] is True
        return Response([b'1234', b'', b'56789'])

    monkeypatch.setattr(assets.requests, 'get', get)
    assert assets.download_model(arch, str(tmp_path)) == 18
    assert (tmp_path / 'adapter.ort').read_bytes() == b'123456789'
    assert (tmp_path / 'tokenizer.bin').read_bytes() == b'123456789'
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('chunks', [[b'wronghash'], [b'short'], [b'123456789', b'extra']])
def test_corrupt_or_incomplete_download_never_becomes_ready(
        miniature_models, monkeypatch, tmp_path, chunks):
    assets = miniature_models
    monkeypatch.setattr(assets.requests, 'get', lambda *a, **kw: Response(chunks))

    with pytest.raises(RuntimeError, match='(checksum|size)'):
        assets.download_model('tiny-streaming', str(tmp_path))
    assert not (tmp_path / 'adapter.ort').exists()
    assert not list(tmp_path.glob('*.part'))


def test_network_failure_removes_partial_file(miniature_models, monkeypatch, tmp_path):
    assets = miniature_models

    def broken_stream():
        yield b'123'
        raise assets.requests.ConnectionError('interrupted')

    monkeypatch.setattr(assets.requests, 'get', lambda *a, **kw: Response(broken_stream()))
    with pytest.raises(assets.requests.ConnectionError):
        assets.download_model('tiny-streaming', str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_insufficient_disk_prevents_network_and_file_writes(
        miniature_models, monkeypatch, tmp_path):
    assets = miniature_models
    monkeypatch.setattr(assets.shutil, 'disk_usage', lambda path: SimpleNamespace(free=17))
    monkeypatch.setattr(assets.requests, 'get', lambda *a, **kw: pytest.fail('network used'))

    with pytest.raises(OSError, match='space'):
        assets.download_model('tiny-streaming', str(tmp_path))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('filename', ['../outside.ort', '/absolute.ort', r'..\outside.ort', 'C:outside.ort'])
def test_manifest_paths_cannot_escape_managed_directory(
        miniature_models, monkeypatch, tmp_path, filename):
    assets = miniature_models
    monkeypatch.setitem(assets._MODELS, 'tiny-streaming', (assets.Asset(filename, 9, '4waSgw=='),))
    monkeypatch.setattr(assets.requests, 'get', lambda *a, **kw: pytest.fail('network used'))

    with pytest.raises(ValueError, match='filename'):
        assets.download_model('tiny-streaming', str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_crc32c_fallback_matches_standard_vector():
    from services import moonshine_assets as assets

    assert assets._crc32c(b'123456789') == 0xE3069283
    crc = assets._crc32c(b'1234')
    assert assets._crc32c(b'56789', crc) == 0xE3069283


def test_missing_files_rejects_nonempty_truncated_assets(miniature_models, tmp_path):
    assets = miniature_models
    (tmp_path / 'adapter.ort').write_bytes(b'x')
    (tmp_path / 'tokenizer.bin').write_bytes(b'123456789')

    assert assets.missing_files('tiny-streaming', str(tmp_path)) == ['adapter.ort']


def test_missing_files_checks_sizes_without_hashing(miniature_models, monkeypatch, tmp_path):
    assets = miniature_models
    (tmp_path / 'adapter.ort').write_bytes(b'123456789')
    (tmp_path / 'tokenizer.bin').write_bytes(b'123456789')
    monkeypatch.setattr(assets, '_verified', lambda *a: pytest.fail('hashed readiness assets'))

    assert assets.missing_files('tiny-streaming', str(tmp_path)) == []


def test_missing_files_reports_absent_directory_without_creating_it(miniature_models, tmp_path):
    assets = miniature_models
    target = tmp_path / 'not-installed'

    assert assets.missing_files('tiny-streaming', str(target)) == ['adapter.ort', 'tokenizer.bin']
    assert not target.exists()
