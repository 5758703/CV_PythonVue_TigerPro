"""TTS 模型下拉：按 task 全量 options，且能力字段随 library 声明。"""
import unittest

from models.ai_model import TTS_CLONE_LIBS, TTS_CLONE_REQUIRED_LIBS, AiModel


class TtsCapabilityDictTest(unittest.TestCase):
    def test_neutts_clone_flags(self):
        m = AiModel(
            model_name="NeuTTS",
            model_key="neutts-air",
            task="text-to-speech",
            library="neutts",
            status="0",
            file_path="models/neutts-air",
        )
        d = m.to_dict()
        self.assertTrue(d["ttsClone"])
        self.assertTrue(d["ttsCloneRequired"])
        self.assertIn("neutts", TTS_CLONE_LIBS)
        self.assertIn("neutts", TTS_CLONE_REQUIRED_LIBS)

    def test_voxcpm_optional_clone(self):
        m = AiModel(
            model_name="VoxCPM",
            model_key="voxcpm",
            task="text-to-speech",
            library="voxcpm",
            status="0",
            file_path="models/voxcpm",
        )
        d = m.to_dict()
        self.assertTrue(d["ttsClone"])
        self.assertFalse(d["ttsCloneRequired"])

    def test_non_tts_has_no_clone_flags(self):
        m = AiModel(
            model_name="YOLO",
            model_key="yolo26n",
            task="object-detection",
            library="ultralytics",
            status="0",
            file_path="models/yolo26n.pt",
        )
        d = m.to_dict()
        self.assertNotIn("ttsClone", d)
        self.assertNotIn("ttsCloneRequired", d)


if __name__ == "__main__":
    unittest.main()
