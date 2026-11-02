import importlib.util
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('video_limits',Path(__file__).resolve().parents[1]/'nonebot_plugin_mortis_analysis/video_limits.py')
LIMITS=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIMITS)


class VideoLimitTests(unittest.TestCase):
    def test_size_boundary(self):
        LIMITS.check_size(80*1024*1024,80*1024*1024)
        with self.assertRaises(LIMITS.VideoLimitExceeded) as error:
            LIMITS.check_size(80*1024*1024+1,80*1024*1024)
        self.assertEqual(error.exception.reason,'size')

    def test_duration_boundary_and_missing_metadata(self):
        for value in (None,0,'unknown',480):
            LIMITS.check_duration(value,480)
        with self.assertRaises(LIMITS.VideoLimitExceeded) as error:
            LIMITS.check_duration(480.01,480)
        self.assertEqual(error.exception.reason,'duration')


if __name__=='__main__':
    unittest.main()
