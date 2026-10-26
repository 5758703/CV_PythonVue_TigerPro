"""HF direct downloads are pinned and hashed; HTTP is the only mocked I/O."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest


REVISION = '536b0662742c02347bc0e980a01041f333bce120'
REQUIRED = ('model.bin', 'tokenizer/vocab.json')
PAYLOAD = b'hello\n'
SHA256 = '5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03'
GIT_BLOB = 'ce013625030ba8dba906f756967f9e9ca394464a'


class Response:
    def __init__(self, *, payload=None, chunks=()):
        self.payload = payload
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        yield from self.chunks


@pytest.fixture
def hf(monkeypatch):
    from services import cpu_asr_hf_assets as assets

    manifest = {'sha': REVISION, 'siblings': [
        {'rfilename': 'model.bin', 'size': 6, 'blobId': 'a' * 40,
         'lfs': {'sha256': SHA256, 'size': 6, 'pointerSize': 126}},
        {'rfilename': 'tokenizer/vocab.json', 'size': 6, 'blobId': GIT_BLOB},
        {'rfilename': 'README.md', 'size': 3, 'blobId': 'b' * 40},
    ]}
    monkeypatch.setattr(assets.shutil, 'disk_usage', lambda path: SimpleNamespace(free=10**9))
    return assets, manifest


def fake_http(monkeypatch, assets, manifest, *, chunks=(b'hel', b'', b'lo\n'), downloads=None):
    def get(url, **kwargs):
        parsed = urlsplit(url)
        if parsed.path == '/api/models/example/asr':
            assert parse_qs(parsed.query)['blobs'] == ['true']
            return Response(payload=manifest)
        assert parsed.scheme == 'https' and parsed.netloc == 'huggingface.co'
        assert parsed.path.startswith(f'/example/asr/resolve/{REVISION}/')
        assert parse_qs(parsed.query)['download'] == ['true']
        assert kwargs['stream'] is True
        filename = parsed.path.split(f'/{REVISION}/', 1)[1]
        assert filename in REQUIRED
        if downloads is not None:
            downloads.append(filename)
        return Response(chunks=chunks)
    monkeypatch.setattr(assets.requests, 'get', get)


def test_download_freezes_revision_and_verifies_lfs_and_git_blobs(hf, monkeypatch, tmp_path):
    assets, manifest = hf
    fake_http(monkeypatch, assets, manifest)

    assert assets.download_hf_files('example/asr', str(tmp_path), REQUIRED) == 12
    assert (tmp_path / 'model.bin').read_bytes() == PAYLOAD
    assert (tmp_path / 'tokenizer/vocab.json').read_bytes() == PAYLOAD
    assert not (tmp_path / 'README.md').exists()
    assert not list(tmp_path.rglob('*.part'))


def test_existing_files_are_skipped_only_after_hash_validation(hf, monkeypatch, tmp_path):
    assets, manifest = hf
    (tmp_path / 'model.bin').write_bytes(PAYLOAD)
    (tmp_path / 'tokenizer').mkdir()
    (tmp_path / 'tokenizer/vocab.json').write_bytes(b'broken')
    downloads = []
    fake_http(monkeypatch, assets, manifest, downloads=downloads)

    assert assets.download_hf_files('example/asr', str(tmp_path), REQUIRED) == 12
    assert downloads == ['tokenizer/vocab.json']
    assert (tmp_path / 'tokenizer/vocab.json').read_bytes() == PAYLOAD


@pytest.mark.parametrize('filename', REQUIRED)
def test_same_size_corruption_never_becomes_final(hf, monkeypatch, tmp_path, filename):
    assets, manifest = hf
    fake_http(monkeypatch, assets, manifest, chunks=[b'broken'])

    with pytest.raises(RuntimeError, match='(hash|checksum)'):
        assets.download_hf_files('example/asr', str(tmp_path), (filename,))
    assert not (tmp_path / filename).exists()
    assert not list(tmp_path.rglob('*.part'))


@pytest.mark.parametrize('chunks', [[b'short'], [PAYLOAD, b'excess']])
def test_partial_or_oversize_download_is_not_published(hf, monkeypatch, tmp_path, chunks):
    assets, manifest = hf
    (tmp_path / 'model.bin').write_bytes(b'broken')
    fake_http(monkeypatch, assets, manifest, chunks=chunks)

    with pytest.raises(RuntimeError, match='size'):
        assets.download_hf_files('example/asr', str(tmp_path), ('model.bin',))
    assert not (tmp_path / 'model.bin').exists()
    assert not list(tmp_path.rglob('*.part'))


def test_interrupted_http_stream_cleans_partial(hf, monkeypatch, tmp_path):
    assets, manifest = hf
    def interrupted():
        yield b'hel'
        raise assets.requests.ConnectionError('interrupted')
    fake_http(monkeypatch, assets, manifest, chunks=interrupted())

    with pytest.raises(assets.requests.ConnectionError):
        assets.download_hf_files('example/asr', str(tmp_path), ('model.bin',))
    assert not list(tmp_path.rglob('*.part'))
    assert not (tmp_path / 'model.bin').exists()


@pytest.mark.parametrize('name', ['../escape', '/absolute', r'..\escape', 'C:escape', 'tokenizer/../escape'])
def test_required_path_traversal_rejected_before_http(hf, monkeypatch, tmp_path, name):
    assets, _ = hf
    monkeypatch.setattr(assets.requests, 'get', lambda *a, **kw: pytest.fail('network used'))

    with pytest.raises(ValueError, match='(path|filename)'):
        assets.download_hf_files('example/asr', str(tmp_path), (name,))
    assert not list(tmp_path.iterdir())


def test_insufficient_space_stops_before_weight_download(hf, monkeypatch, tmp_path):
    assets, manifest = hf
    monkeypatch.setattr(assets.shutil, 'disk_usage', lambda path: SimpleNamespace(free=11))
    fake_http(monkeypatch, assets, manifest)

    with pytest.raises(OSError, match='space'):
        assets.download_hf_files('example/asr', str(tmp_path), REQUIRED)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('fault', ['revision', 'missing', 'lfs-hash', 'git-hash', 'size'])
def test_unverifiable_manifest_fails_before_asset_creation(hf, monkeypatch, tmp_path, fault):
    assets, manifest = hf
    if fault == 'revision':
        manifest['sha'] = 'main'
    elif fault == 'missing':
        manifest['siblings'].pop(1)
    elif fault == 'lfs-hash':
        manifest['siblings'][0]['lfs'].pop('sha256')
    elif fault == 'git-hash':
        manifest['siblings'][1]['blobId'] = 'invalid'
    else:
        manifest['siblings'][0]['size'] = -1
    fake_http(monkeypatch, assets, manifest)

    with pytest.raises(ValueError):
        assets.download_hf_files('example/asr', str(tmp_path), REQUIRED)
    assert not list(tmp_path.iterdir())


def test_all_verified_files_need_no_extra_space_or_weight_request(hf, monkeypatch, tmp_path):
    assets, manifest = hf
    (tmp_path / 'model.bin').write_bytes(PAYLOAD)
    (tmp_path / 'tokenizer').mkdir()
    (tmp_path / 'tokenizer/vocab.json').write_bytes(PAYLOAD)
    monkeypatch.setattr(assets.shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    downloads = []
    fake_http(monkeypatch, assets, manifest, downloads=downloads)

    assert assets.download_hf_files('example/asr', str(tmp_path), REQUIRED) == 12
    assert downloads == []


def test_optional_token_is_passed_to_http_boundary(hf, monkeypatch, tmp_path):
    assets, manifest = hf
    fake_http(monkeypatch, assets, manifest)
    original_get = assets.requests.get
    def authorized_get(url, **kwargs):
        assert kwargs['headers']['Authorization'] == 'Bearer private-fixture-token'
        return original_get(url, **kwargs)
    monkeypatch.setattr(assets.requests, 'get', authorized_get)

    assert assets.download_hf_files('example/asr', str(tmp_path), REQUIRED,
                                    token='private-fixture-token') == 12


def test_symlinked_parent_cannot_redirect_download_outside_target(hf, monkeypatch, tmp_path):
    assets, _ = hf
    root = tmp_path / 'managed'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    try:
        (root / 'tokenizer').symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'Creating symlinks is unavailable: {exc}')
    monkeypatch.setattr(assets.requests, 'get', lambda *a, **kw: pytest.fail('network used'))

    with pytest.raises(ValueError, match='path'):
        assets.download_hf_files('example/asr', str(root), ('tokenizer/vocab.json',))
    assert not list(outside.iterdir())


def test_progress_is_emitted_at_download_threshold(hf, monkeypatch, tmp_path, capsys):
    assets, manifest = hf
    monkeypatch.setattr(assets, '_PROGRESS_BYTES', 4)
    fake_http(monkeypatch, assets, manifest)

    assets.download_hf_files('example/asr', str(tmp_path), ('model.bin',))
    assert 'example/asr/model.bin:' in capsys.readouterr().out
