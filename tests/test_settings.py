import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1]/'nonebot_plugin_mortis_analysis/settings.py'
SPEC = importlib.util.spec_from_file_location('analysis_settings', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SettingsTests(unittest.TestCase):
    def test_no_credentials_or_write_api_required(self):
        store = MODULE.RuntimeSettings()
        self.assertTrue(store.current()['enabled'])
        self.assertFalse(any(store.current()[key] for key in MODULE.SECRETS))
        self.assertFalse(hasattr(store, 'update'))

    def test_environment_snapshot_is_independent(self):
        values = {'xhs_ck':'configured', 'blocked_platforms':['dy']}
        store = MODULE.RuntimeSettings(values)
        values['blocked_platforms'].clear()
        state = store.current()
        self.assertEqual(state['xhs_ck'], 'configured')
        self.assertEqual(state['blocked_platforms'], ['dy'])
        state['blocked_platforms'].clear()
        self.assertEqual(store.current()['blocked_platforms'], ['dy'])


if __name__ == '__main__':
    unittest.main()
