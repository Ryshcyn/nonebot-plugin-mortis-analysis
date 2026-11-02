"""Verify both process environment and dotenv configuration in fresh processes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VALUES = {
    'MORTIS_ANALYSIS_ENABLED':'false',
    'MORTIS_ANALYSIS_HOT_COMMENT_COUNT':'3',
    'MORTIS_ANALYSIS_VIDEO_MAX_DURATION':'120',
    'MORTIS_ANALYSIS_VIDEO_MAX_SIZE_MB':'40',
    'MORTIS_ANALYSIS_XHS_CK':'offline-dummy',
}

if len(sys.argv) == 1:
    env = {key:value for key,value in os.environ.items() if not key.upper().startswith(('MORTIS_ANALYSIS_','MORTIS_RESOLVER_'))}
    for mode in ('environment','dotenv'):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), mode],env=env,check=True)
    print('PASS: NoneBot environment and dotenv configuration without settings write API')
else:
    if not os.environ.get('CHECK_INSTALLED_WHEEL'):
        sys.path.insert(0,str(ROOT))
    with tempfile.TemporaryDirectory(prefix='analysis-env-') as directory:
        os.chdir(directory)
        if sys.argv[1] == 'environment':
            os.environ.update(VALUES)
        else:
            Path('.env').write_text('\n'.join(key+'='+value for key,value in VALUES.items()))
        import nonebot
        nonebot.init(driver='~fastapi',_env_file='.env' if sys.argv[1]=='dotenv' else None,
                     localstore_use_cwd=True,log_level='WARNING')
        assert nonebot.load_plugin('nonebot_plugin_mortis_analysis') is not None
        from nonebot_plugin_mortis_analysis.settings import get_store
        store = get_store()
        value = store.current()
        assert value['enabled'] is False and value['hot_comment_count'] == 3
        assert value['video_max_duration'] == 120 and value['video_max_size_mb'] == 40
        assert value['xhs_ck'] == 'offline-dummy'
        assert not hasattr(store,'update')
