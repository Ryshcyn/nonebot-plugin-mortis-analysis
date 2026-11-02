"""Check metadata, dependencies, async HTTP, resource packaging and zero-config loading."""
import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from unittest.mock import patch

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'nonebot_plugin_mortis_analysis'
PROJECT = 'nonebot-plugin-mortis-analysis'
project = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']
assert project['name'] == PROJECT
assert project['urls']['Homepage'] == 'https://github.com/Ryshcyn/'+PROJECT
assert all('==' not in value for value in project['dependencies'])
declared = {re.split(r'[<>=!~;\[]', value)[0].lower().replace('_','-') for value in project['dependencies']}
aliases = {'nonebot':'nonebot2','PIL':'pillow','bilibili_api':'bilibili-api-python','execjs':'pyexecjs'}
for file in (ROOT/MODULE).rglob('*.py'):
    for node in ast.walk(ast.parse(file.read_text())):
        modules = []
        if isinstance(node,ast.Import):
            modules = [item.name.split('.')[0] for item in node.names]
        elif isinstance(node,ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module.split('.')[0]]
        for name in modules:
            if name in sys.stdlib_module_names:
                continue
            dependency = aliases.get(name,name).lower().replace('_','-')
            assert dependency in declared, (file,name,'missing direct dependency')
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name):
            assert not (node.func.value.id in {'httpx','requests'} and node.func.attr in {'get','post','head','request'}), (file,'synchronous HTTP')

if not os.environ.get('CHECK_INSTALLED_WHEEL'):
    sys.path.insert(0,str(ROOT))
with tempfile.TemporaryDirectory(prefix='resolver-zero-config-') as directory:
    original = Path.cwd()
    try:
        os.chdir(directory)
        import nonebot
        nonebot.init(driver='~fastapi',_env_file=None,localstore_use_cwd=True,log_level='WARNING')
        original_popen = subprocess.Popen
        def check_system_program(args, *arguments, **keywords):
            executable = Path(args[0] if not isinstance(args,str) else args.split()[0]).name.lower()
            assert not any(name in executable for name in ('ffmpeg','ffprobe','node','chromium','chrome','playwright')), 'Plugin import must not start media tools'
            return original_popen(args,*arguments,**keywords)
        with patch('subprocess.Popen', side_effect=check_system_program):
            plugin = nonebot.load_plugin(MODULE)
        assert plugin is not None
        meta = plugin.metadata
        assert meta and meta.type == 'application' and meta.config is not None
        legacy_config = meta.config.model_validate({'mortis_resolver_enabled':False, 'mortis_resolver_video_max_duration':321})
        assert legacy_config.mortis_analysis_enabled is False and legacy_config.mortis_analysis_video_max_duration == 321
        preferred_config = meta.config.model_validate({'mortis_analysis_enabled':True, 'mortis_resolver_enabled':False})
        assert preferred_config.mortis_analysis_enabled is True
        assert meta.name and meta.description and meta.usage
        assert meta.homepage == project['urls']['Homepage']
        adapters = {('nonebot.adapters.'+value[1:]) if value.startswith('~') else value for value in meta.supported_adapters}
        assert adapters == {'nonebot.adapters.onebot.v11'}
        if os.environ.get('CHECK_INSTALLED_WHEEL'):
            assert not Path(plugin.module.__file__).resolve().is_relative_to(ROOT), 'Loaded checkout instead of installed wheel'
        storage = __import__(MODULE+'.storage',fromlist=['DATA_DIR'])
        for path in (storage.DATA_DIR,storage.CONFIG_DIR,storage.CACHE_DIR):
            assert path.resolve().is_relative_to(Path(directory))
        settings = __import__(MODULE+'.settings',fromlist=['get_store'])
        assert not any(settings.get_store().current().get(key) for key in settings.SECRETS)
        assert not hasattr(settings.get_store(), 'update')
    finally:
        os.chdir(original)

license_prefix = MODULE+'-'+project['version']+'.dist-info/licenses/'
required = {MODULE+'/card.html',MODULE+'/core/a-bogus.js'} | {
    license_prefix+name for name in ('LICENSE',)}
for wheel in (ROOT/'dist').glob('*.whl'):
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert required <= names
        bundled_license = archive.read(license_prefix+'LICENSE').decode()
        assert 'Mulan Permissive Software License' in bundled_license
        assert not any(name.startswith(MODULE+'/') and name.endswith(('.md','.txt')) for name in names)
        assert not any(name.endswith(('.pyc','settings.json','cookies.txt')) for name in names)

tag = os.environ.get('RELEASE_TAG')
if tag:
    assert tag == 'v'+project['version'], 'Release tag does not match project version'
print('PASS: zero-credential load, metadata, direct dependencies, async HTTP, localstore and packaged resources')
