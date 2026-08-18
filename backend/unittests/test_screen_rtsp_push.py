"""screen_rtsp_push 单元测试。"""
import unittest
from unittest.mock import patch

from services import screen_rtsp_push


class ScreenRtspPushTest(unittest.TestCase):
    def test_sanitize_stream_name(self):
        self.assertEqual(screen_rtsp_push._sanitize_stream_name("my-screen_1"), "my-screen_1")
        self.assertEqual(screen_rtsp_push._sanitize_stream_name("  hello world!  "), "helloworld")
        self.assertEqual(screen_rtsp_push._sanitize_stream_name(""), "desktop")

    def test_build_rtsp_url(self):
        url = screen_rtsp_push.build_rtsp_url("localhost", 8554, "desktop")
        self.assertEqual(url, "rtsp://localhost:8554/desktop")

    @patch("services.screen_rtsp_push.is_windows", return_value=True)
    @patch("services.screen_rtsp_push._get_ffmpeg_exe", return_value="ffmpeg.exe")
    def test_build_screen_push_cmd(self, _exe, _win):
        cmd = screen_rtsp_push.build_screen_push_cmd(
            rtsp_url="rtsp://localhost:8554/desktop",
            fps=15,
            width=640,
        )
        self.assertIn("gdigrab", cmd)
        self.assertIn("desktop", cmd)
        self.assertIn("rtsp://localhost:8554/desktop", cmd)
        self.assertIn("libx264", cmd)

    @patch("services.screen_rtsp_push.is_windows", return_value=False)
    def test_preview_command_non_windows(self, _win):
        data = screen_rtsp_push.preview_command()
        self.assertFalse(data["supported"])


if __name__ == "__main__":
    unittest.main()
