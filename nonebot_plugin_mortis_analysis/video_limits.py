"""Fast video eligibility checks; never transcode or silently truncate media."""
import re


class VideoLimitExceeded(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Video limit exceeded: '+reason)


def check_size(size, maximum):
    if size > maximum:
        raise VideoLimitExceeded('size')


def check_duration(duration, maximum):
    try:
        value = float(duration or 0)
    except (ValueError, TypeError):
        return
    if value > maximum:
        raise VideoLimitExceeded('duration')


def maximum_bytes():
    from .settings import get_store
    return get_store().current()['video_max_size_mb'] * 1024 * 1024


def check_metadata(duration):
    from .settings import get_store
    check_duration(duration, get_store().current()['video_max_duration'])


async def send_limit_notice(bot, event, error):
    from . import send_both
    from .settings import get_store
    from nonebot.adapters.onebot.v11 import MessageSegment
    values = get_store().current()
    if error.reason == 'duration':
        reason = f'视频超过时长上限（{values["video_max_duration"]/60:g} 分钟）'
    else:
        reason = f'视频超过大小上限（{values["video_max_size_mb"]} MB）'
    match = re.search(r'https?://[^\s<>"\]]+', str(event.message))
    link = match.group().rstrip('，。！？；：）】》') if match else ''
    text = reason+'，仅发送作品信息，请通过原链接观看。'
    if link:
        text += '\n原链接：'+link
    await send_both(bot, event, MessageSegment.text(text))
