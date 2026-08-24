"""core.logic.photo_export 单元测试。"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

from core.logic.photo_export import (
    select_frames,
    _draw_watermark,
    _process_frame,
    export_timelapse,
    DEFAULT_MAX_FRAMES,
)


class PhotoExportTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.photo_dir = os.path.join(self.temp_dir, "photos")
        self.thumb_dir = os.path.join(self.photo_dir, "thumbs")
        self.cache_dir = os.path.join(self.temp_dir, "cache", "export")
        os.makedirs(self.photo_dir, exist_ok=True)
        os.makedirs(self.thumb_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_select_frames_under_limit(self):
        photos = [(f"2026-08-{i:02d}", f"2026-08-{i:02d}.jpg") for i in range(1, 11)]
        selected = select_frames(photos, max_frames=20)
        self.assertEqual(len(selected), 10)
        self.assertEqual(selected, photos)

    def test_select_frames_over_limit_preserves_endpoints(self):
        photos = [(f"2026-01-{i:03d}", f"photo_{i}.jpg") for i in range(1, 201)]
        selected = select_frames(photos, max_frames=50)
        self.assertEqual(len(selected), 50)
        # First and last must be preserved exactly
        self.assertEqual(selected[0], photos[0])
        self.assertEqual(selected[-1], photos[-1])

    def test_process_frame_enforces_even_dimensions(self):
        # Create a test image with odd dimensions (e.g. 501 x 333)
        img_path = os.path.join(self.photo_dir, "test_odd.jpg")
        img = Image.new("RGB", (501, 333), color="green")
        img.save(img_path, "JPEG")

        processed = _process_frame(img_path, "2026-08-24", target_max_dim=1920, watermark=True)
        self.assertIsNotNone(processed)
        w, h = processed.size
        self.assertEqual(w % 2, 0, f"Width {w} must be even")
        self.assertEqual(h % 2, 0, f"Height {h} must be even")

    def test_draw_watermark_runs_cleanly(self):
        img = Image.new("RGB", (640, 480), color="blue")
        watermarked = _draw_watermark(img, "2026-08-24")
        self.assertIsNotNone(watermarked)
        self.assertEqual(watermarked.size, (640, 480))

    def test_export_timelapse_invalid_parameters(self):
        with self.assertRaises(ValueError):
            export_timelapse(export_format="avi")

        with self.assertRaises(ValueError):
            export_timelapse(quality="ultra_hd")

    @patch("core.database.query_photos_asc")
    def test_export_timelapse_empty_photos_raises_value_error(self, mock_query):
        mock_query.return_value = []
        with self.assertRaises(ValueError) as ctx:
            export_timelapse(export_format="mp4")
        self.assertIn("No photos found", str(ctx.exception))

    @patch("core.database.query_photos_asc")
    def test_export_timelapse_gif_with_pillow_fallback(self, mock_query):
        import core.state as state
        with patch.object(state, "PHOTO_DIR", self.photo_dir), \
             patch.object(state, "THUMB_DIR", self.thumb_dir), \
             patch.object(state, "EXPORT_CACHE_DIR", self.cache_dir):

            # Create 3 dummy photos
            dates = ["2026-08-01", "2026-08-02", "2026-08-03"]
            rows = []
            for d in dates:
                fn = f"{d}.jpg"
                p = os.path.join(self.photo_dir, fn)
                Image.new("RGB", (320, 240), color="red").save(p, "JPEG")
                rows.append((d, fn))

            mock_query.return_value = rows

            # Force shutil.which("ffmpeg") to return None to test Pillow GIF fallback
            with patch("shutil.which", return_value=None):
                output_path = export_timelapse(export_format="gif", quality="sd", fps=2.0, watermark=True)
                self.assertTrue(os.path.exists(output_path))
                self.assertTrue(output_path.endswith(".gif"))
                self.assertGreater(os.path.getsize(output_path), 0)

    @patch("core.database.query_photos_asc")
    def test_export_timelapse_mp4_ffmpeg_pipeline(self, mock_query):
        import core.state as state
        with patch.object(state, "PHOTO_DIR", self.photo_dir), \
             patch.object(state, "THUMB_DIR", self.thumb_dir), \
             patch.object(state, "EXPORT_CACHE_DIR", self.cache_dir):

            dates = ["2026-08-01", "2026-08-02"]
            rows = []
            for d in dates:
                fn = f"{d}.jpg"
                p = os.path.join(self.photo_dir, fn)
                Image.new("RGB", (640, 480), color="blue").save(p, "JPEG")
                rows.append((d, fn))

            mock_query.return_value = rows

            # Mock subprocess to verify stdin pipe & communicate without flush errors
            mock_proc = MagicMock()
            mock_stdin = MagicMock()
            mock_proc.stdin = mock_stdin
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")

            def mock_popen(cmd, *args, **kwargs):
                # simulate output file creation by ffmpeg
                out_file = cmd[-1]
                with open(out_file, "wb") as f:
                    f.write(b"fake_mp4_content")
                return mock_proc

            with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
                 patch("subprocess.Popen", side_effect=mock_popen):
                output_path = export_timelapse(export_format="mp4", quality="hd", fps=2.0, watermark=True)
                self.assertTrue(os.path.exists(output_path))
                self.assertTrue(output_path.endswith(".mp4"))
                mock_stdin.close.assert_called_once()
                mock_proc.communicate.assert_called_once()


