import asyncio
import platform
import subprocess

import aiofiles
import shutil
import httpx
from nonebot import logger

from ..constants import BILIBILI_HEADER


async def is_ffmpeg_installed():
    """检查ffmpeg是否安装"""

    # 检查ffmpeg是否在环境变量中
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return True
    
    # 如果仍然未找到，尝试异步调用ffmpeg命令
    try:
        # 根据操作系统选择合适的命令
        if platform.system() == "Windows":
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
        else:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
        await process.wait()
        if process.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"检查ffmpeg时发生错误: {e}")

    return False

async def download_b_file(url, full_file_name, progress_callback, max_bytes=None):
    """
        下载视频文件和音频文件
    :param url:
    :param full_file_name:
    :param progress_callback:
    :return:
    """
    from ..video_limits import maximum_bytes, check_size
    if max_bytes is None:
        max_bytes = maximum_bytes()
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0")) as client:
        async with client.stream("GET", url, headers=BILIBILI_HEADER) as resp:
            resp.raise_for_status()
            current_len = 0
            total_len = int(resp.headers.get('content-length', 0))
            check_size(total_len, max_bytes)
            async with aiofiles.open(full_file_name, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    current_len += len(chunk)
                    check_size(current_len, max_bytes)
                    await f.write(chunk)
                    if total_len:
                        progress_callback(f'下载进度：{round(current_len / total_len, 3)}')


async def merge_file_to_mp4(v_full_file_name: str, a_full_file_name: str, output_file_name: str, log_output: bool = False):
    """
    合并视频文件和音频文件
    :param v_full_file_name: 视频文件路径
    :param a_full_file_name: 音频文件路径
    :param output_file_name: 输出文件路径
    :param log_output: 是否显示 ffmpeg 输出日志，默认忽略
    :return:
    """
    logger.info(f'正在合并：{output_file_name}')

    # 检查 ffmpeg 是否安装
    if not await is_ffmpeg_installed():
        logger.error('ffmpeg 未安装，请先安装 ffmpeg 并配置环境变量。可参考插件主页说明。')
        return

    stdout = None if log_output else asyncio.subprocess.DEVNULL
    stderr = None if log_output else asyncio.subprocess.DEVNULL
    process = await asyncio.create_subprocess_exec(
        'ffmpeg', '-y', '-i', v_full_file_name, '-i', a_full_file_name,
        '-c', 'copy', output_file_name, stdout=stdout, stderr=stderr)
    if await process.wait():
        raise RuntimeError('FFmpeg media merge failed')


def extra_bili_info(video_info):
    """
        格式化视频信息
    """
    video_state = video_info['stat']
    video_like, video_coin, video_favorite, video_share, video_view, video_danmaku, video_reply = video_state['like'], \
        video_state['coin'], video_state['favorite'], video_state['share'], video_state['view'], video_state['danmaku'], \
        video_state['reply']

    video_data_map = {
        "点赞": video_like,
        "硬币": video_coin,
        "收藏": video_favorite,
        "分享": video_share,
        "总播放量": video_view,
        "弹幕数量": video_danmaku,
        "评论": video_reply
    }

    video_info_result = ""
    for key, value in video_data_map.items():
        if int(value) > 10000:
            formatted_value = f"{value / 10000:.1f}万"
        else:
            formatted_value = value
        video_info_result += f"{key}: {formatted_value} | "

    return video_info_result
