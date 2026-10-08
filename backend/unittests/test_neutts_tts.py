"""NeuTTS Air 音色克隆适配器：入参校验（不加载真实权重）。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class NeuttsCloneValidationTest(unittest.TestCase):
    def test_rejects_empty_inputs(self):
        from inference import synthesize_speech_neutts_clone

        with self.assertRaises(ValueError):
            synthesize_speech_neutts_clone("/tmp/m", "", "ref", "/tmp/a.wav")
        with self.assertRaises(ValueError):
            synthesize_speech_neutts_clone("/tmp/m", "hi", "", "/tmp/a.wav")
        with self.assertRaises(ValueError):
            synthesize_speech_neutts_clone("/tmp/m", "hi", "ref", "/no/such.wav")

    def test_clone_happy_path_mocked(self):
        from inference import synthesize_speech_neutts_clone

        wav = __import__("numpy").zeros(2400, dtype="float32")
        fake = MagicMock()
        fake.encode_reference.return_value = "codes"
        fake.infer.return_value = wav
        fake.sample_rate = 24000

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            prompt = f.name
        try:
            with patch("inference._get_neutts", return_value=fake), \
                    patch.dict("sys.modules", {"soundfile": MagicMock()}):
                import sys
                sys.modules["soundfile"].write = MagicMock()
                out = synthesize_speech_neutts_clone(
                    "/models/neutts-air", "Hello there.", "Ref transcript.", prompt
                )
            self.assertIn("audio", out)
            self.assertEqual(out["sampleRate"], 24000)
            self.assertEqual(out["speaker"], "clone")
            fake.encode_reference.assert_called_once_with(prompt)
            fake.infer.assert_called_once()
        finally:
            try:
                os.remove(prompt)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
