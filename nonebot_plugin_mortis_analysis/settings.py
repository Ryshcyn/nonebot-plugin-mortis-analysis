"""Runtime configuration from NoneBot; no writable settings service."""
from copy import deepcopy

OPTIONS = {'enabled': True, 'nickname': '小睦解析', 'hot_comment_count': 5,
           'blocked_platforms': [], 'video_max_duration': 480, 'video_max_size_mb': 80}
SECRETS = ('bili_sessdata', 'xhs_ck')


class RuntimeSettings:
    def __init__(self, defaults=None):
        self._values = {**deepcopy(OPTIONS), **dict.fromkeys(SECRETS, ''),
                        **deepcopy(defaults or {})}

    def current(self):
        return deepcopy(self._values)


STORE = None


def initialize(defaults=None):
    global STORE
    STORE = RuntimeSettings(defaults)
    return STORE


def get_store():
    if STORE is None:
        raise RuntimeError('Analysis settings not initialized')
    return STORE
