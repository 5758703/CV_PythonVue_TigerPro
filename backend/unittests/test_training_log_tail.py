"""Incremental log reads should not load the whole file."""

from pathlib import Path

from routes.training import _tail_text


def test_log_tail_reads_only_requested_offset(tmp_path, monkeypatch):
    path = tmp_path / "train.log"
    path.write_bytes(b"a" * 200_000 + b"RESULT" + b"z" * 200_000)

    def forbid_full_read(_self):
        raise AssertionError("full-file read is too expensive for log polling")

    monkeypatch.setattr(Path, "read_bytes", forbid_full_read)
    result = _tail_text(path, 200_000, 256)
    assert result["text"].startswith("RESULT")
    assert result["nextOffset"] == 200_256
    assert result["size"] == 400_006
