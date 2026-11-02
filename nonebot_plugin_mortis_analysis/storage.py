"""All writable plugin paths are owned by nonebot-plugin-localstore."""
from nonebot import require

require('nonebot_plugin_localstore')
import nonebot_plugin_localstore as store

DATA_DIR = store.get_plugin_data_dir()
CONFIG_DIR = store.get_plugin_config_dir()
CACHE_DIR = store.get_plugin_cache_dir()
