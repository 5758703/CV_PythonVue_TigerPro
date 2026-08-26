def test_parse_moss_transcript_segments_fallback():
    from inference import _parse_moss_transcript_segments_fallback

    raw = "[0.50][S01]你好[1.20]\n[1.20][S02]大家好[2.80]"
    segs = _parse_moss_transcript_segments_fallback(raw)

    assert len(segs) == 2
    assert segs[0]["speaker"] == "S01"
    assert segs[0]["text"] == "你好"
    assert segs[0]["start"] == 0.5
    assert segs[0]["end"] == 1.2
    assert segs[1]["speaker"] == "S02"
    assert segs[1]["text"] == "大家好"


def test_is_moss_mtd_model_by_dir_name(tmp_path):
    from inference import _is_moss_mtd_model

    p = tmp_path / "moss-transcribe-diarize-0p9b"
    p.mkdir()

    assert _is_moss_mtd_model(str(p)) is True


def test_transcribe_audio_transformers_routes_to_moss(monkeypatch, tmp_path):
    import inference

    model_dir = tmp_path / "moss-transcribe-diarize"
    model_dir.mkdir()
    audio_path = str(tmp_path / "demo.wav")

    monkeypatch.setattr(inference, "_is_moonshine_model", lambda _p: False)
    monkeypatch.setattr(inference, "_is_moss_mtd_model", lambda _p: True)
    monkeypatch.setattr(
        inference,
        "transcribe_audio_moss_diarize",
        lambda _model_dir, _audio_path: {"text": "ok", "language": None, "emotion": None, "events": []},
    )

    out = inference.transcribe_audio_transformers(str(model_dir), audio_path)
    assert out["text"] == "ok"


def test_transcribe_audio_moss_diarize_formats_segments(monkeypatch):
    import inference
    import services.moss_mtd as moss_mtd

    monkeypatch.setattr(
        inference,
        "_get_moss_mtd",
        lambda _model_dir: ("cpu", "float32", object(), object()),
    )
    monkeypatch.setattr(
        moss_mtd,
        "build_transcription_messages",
        lambda audio_path: [{"audio": audio_path}],
    )
    monkeypatch.setattr(
        moss_mtd,
        "generate_transcription",
        lambda model, processor, messages, max_new_tokens=None, do_sample=False, device=None, dtype=None: {
            "text": "[0.50][S01]你好[1.20][1.20][S02]大家好[2.80]"
        },
    )

    out = inference.transcribe_audio_moss_diarize("dummy", "demo.wav")
    assert "[0.50-1.20] S01: 你好" in out["text"]
    assert "[1.20-2.80] S02: 大家好" in out["text"]
    assert len(out["segments"]) == 2


def test_moss_mtd_helpers_do_not_need_official_package():
    import services.moss_mtd as moss_mtd

    msgs = moss_mtd.build_transcription_messages("demo.wav")
    assert msgs[0]["content"][0]["audio"] == "demo.wav"
    assert moss_mtd.resolve_device("cpu").type == "cpu"


def test_extract_audio_wav_invokes_ffmpeg(monkeypatch, tmp_path):
    import subprocess as real_subprocess
    import services.moss_mtd as moss_mtd

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    out = tmp_path / "out.wav"

    class FakeProc:
        returncode = 0
        stderr = b""

    def fake_run(cmd, stdout=None, stderr=None):
        out.write_bytes(b"RIFF" + b"\x00" * 8)
        return FakeProc()

    monkeypatch.setattr(moss_mtd.subprocess, "run", fake_run)
    monkeypatch.setattr("imageio_ffmpeg.get_ffmpeg_exe", lambda: "ffmpeg")
    path = moss_mtd.extract_audio_wav(str(media), str(out))
    assert path == str(out)
    assert out.is_file()
    assert real_subprocess.PIPE is not None
