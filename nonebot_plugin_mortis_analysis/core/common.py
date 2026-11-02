import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4
from typing import List, Dict, Any
from urllib.parse import urlparse
from nonebot import require, logger

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store

from ..storage import CACHE_DIR, DATA_DIR

import aiofiles
import aiohttp
import httpx

from ..constants import COMMON_HEADER, PLUGIN_NAME, RESOLVE_SHUTDOWN_LIST_NAME


def control_file(name):
    target = DATA_DIR / name
    if not target.exists():
        for legacy in (store.get_data_file(PLUGIN_NAME, name), store.get_data_file('nonebot_plugin_mortis_resolver', name), store.get_data_file('nonebot-plugin-resolver', name)):
            if legacy.exists():
                target.write_bytes(legacy.read_bytes())
                break
    return target


async def download_video(url, proxy: str = None, ext_headers=None, max_bytes=None) -> str:
    """
    异步下载（httpx）视频，并支持通过代理下载。
    文件名将使用时间戳生成，以确保唯一性。
    如果提供了代理地址，则会通过该代理下载视频。

    :param ext_headers:
    :param url: 要下载的视频的URL。
    :param proxy: 可选，下载视频时使用的代理服务器的URL。
    :return: 保存视频的路径。
    """
    # 使用时间戳生成文件名，确保唯一性
    path = str(CACHE_DIR / (uuid4().hex + ".mp4"))
    from ..video_limits import maximum_bytes, check_size, VideoLimitExceeded
    if max_bytes is None:
        max_bytes = maximum_bytes()

    # 判断 ext_headers 是否为 None
    if ext_headers is None:
        headers = COMMON_HEADER
    else:
        # 使用 update 方法合并两个字典
        headers = COMMON_HEADER.copy()  # 先复制 COMMON_HEADER
        headers.update(ext_headers)  # 然后更新 ext_headers

    # 配置代理
    client_config = {
        'headers': headers,
        'timeout': httpx.Timeout(60, connect=5.0),
        'follow_redirects': True
    }
    if proxy:
        client_config['proxy'] = proxy

    # 下载文件
    try:
        async with httpx.AsyncClient(**client_config) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                check_size(int(resp.headers.get('content-length') or 0), max_bytes)
                received = 0
                async with aiofiles.open(path, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        received += len(chunk)
                        check_size(received, max_bytes)
                        await f.write(chunk)
        return path
    except VideoLimitExceeded:
        Path(path).unlink(missing_ok=True)
        raise
    except Exception as e:
        Path(path).unlink(missing_ok=True)
        logger.warning(f"下载视频失败：{type(e).__name__}")
        return None


async def download_img(url: str, path: str = '', proxy: str = None, session=None, headers=None) -> str:
    """
    异步下载（aiohttp）网络图片，并支持通过代理下载。
    如果未指定path，则图片将保存在当前工作目录并以图片的文件名命名。
    如果提供了代理地址，则会通过该代理下载图片。

    :param url: 要下载的图片的URL。
    :param path: 图片保存的路径。如果为空，则保存在当前目录。
    :param proxy: 可选，下载图片时使用的代理服务器的URL。
    :return: 保存图片的路径。
    """
    if path == '':
        path = str(CACHE_DIR / (uuid4().hex + (Path(urlparse(url).path).suffix or '.jpg')))
    # 单个文件下载
    if session is None:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, headers=headers) as response:
                response.raise_for_status()
                if response.status == 200:
                    data = await response.read()
                    async with aiofiles.open(path, 'wb') as f:
                        await f.write(data)
    # 多个文件异步下载
    else:
        async with session.get(url, proxy=proxy, headers=headers) as response:
            response.raise_for_status()
            if response.status == 200:
                data = await response.read()
                async with aiofiles.open(path, 'wb') as f:
                    await f.write(data)
    return path


async def download_audio(url, headers=None):
    # 从URL中提取文件名
    parsed_url = urlparse(url)
    file_name = parsed_url.path.split('/')[-1]
    # 去除可能存在的请求参数
    file_name = file_name.split('?')[0]

    path = str(CACHE_DIR / (uuid4().hex + (Path(file_name).suffix or ".mp3")))

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()  # 检查请求是否成功

        async with aiofiles.open(path, 'wb') as file:
            await file.write(response.content)
    return path


def delete_boring_characters(sentence):
    """
        去除标题的特殊字符
    :param sentence:
    :return:
    """
    return re.sub(r'[0-9’!"∀〃#$%&\'()*+,-./:;<=>?@，。?★、…【】《》？“”‘’！[\\]^_`{|}~～\s]+', "", sentence)


def remove_files(file_paths: List[str]) -> Dict[str, str]:
    """
    根据路径删除文件

    Parameters:
    *file_paths (str): 要删除的一个或多个文件路径

    Returns:
    dict: 一个以文件路径为键、删除状态为值的字典
    """
    results = { }

    for file_path in file_paths:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                results[file_path] = 'remove'
            except Exception as e:
                results[file_path] = f'error: {e}'
        else:
            results[file_path] = 'don\'t exist'

    return results


def get_file_size_mb(file_path):
    """
    判断当前文件的大小是多少MB
    :param file_path:
    :return:
    """
    # 获取文件大小（以字节为单位）
    file_size_bytes = os.path.getsize(file_path)

    # 将字节转换为 MB 并取整
    file_size_mb = int(file_size_bytes / (1024 * 1024))

    return file_size_mb


def load_or_initialize_list() -> List[Any]:
    data_file = control_file(RESOLVE_SHUTDOWN_LIST_NAME)
    # 判断是否存在
    if not data_file.exists():
        data_file.write_text(json.dumps([]))
    return list(json.loads(data_file.read_text()))


def save_sub_user(sub_group):
    """
    使用pickle将对象保存到文件
    :return: None
    """
    data_file = control_file(RESOLVE_SHUTDOWN_LIST_NAME)
    data_file.write_text(json.dumps(sub_group))


def load_sub_user():
    """
    从文件中加载对象
    :return: 订阅用户列表
    """
    data_file = control_file(RESOLVE_SHUTDOWN_LIST_NAME)
    # 判断是否存在
    if not data_file.exists():
        data_file.write_text(json.dumps([]))
    return json.loads(data_file.read_text())


def split_and_strip(text, sep=None) -> List[str]:
    # 先去除两边的空格，然后按指定分隔符分割
    split_text = text.strip().split(sep)
    # 去除每个子字符串两边的空格
    return [sub_text.strip() for sub_text in split_text]

# ==================== 评论配置持久化工具 ====================
COMMENT_SHUTDOWN_LIST_NAME = "comment_shutdown_list.json"
COMMENT_MODE_MAP_NAME = "comment_mode_map.json"

def load_or_initialize_comment_list() -> List[Any]:
    """读取关闭评论的名单"""
    data_file = control_file(COMMENT_SHUTDOWN_LIST_NAME)
    if not data_file.exists():
        data_file.write_text(json.dumps([]))
    return list(json.loads(data_file.read_text()))

def save_comment_list(shutdown_list: list):
    """保存关闭评论的名单"""
    data_file = control_file(COMMENT_SHUTDOWN_LIST_NAME)
    data_file.write_text(json.dumps(shutdown_list))

def load_comment_mode_map() -> dict:
    """读取各群的评论模式 (text/image)"""
    data_file = control_file(COMMENT_MODE_MAP_NAME)
    if not data_file.exists():
        data_file.write_text(json.dumps({}))
    return dict(json.loads(data_file.read_text()))

def save_comment_mode_map(mode_map: dict):
    """保存各群的评论模式"""
    data_file = control_file(COMMENT_MODE_MAP_NAME)
    data_file.write_text(json.dumps(mode_map))


# 分享页请求头、跳转地址和媒体链接校验。
from urllib.parse import parse_qs, unquote
class SkipParse(Exception):
    pass

def _ensure_url_has_scheme(url: str) -> str:
    """确保URL带有scheme，便于urlparse正确解析hostname。"""
    if not url:
        return url
    u = url.strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith(("http://", "https://")):
        return u
    return "https://" + u

def _is_live_url_basic(url: str) -> bool:
    """仅基于hostname标签判断是否为live域名。"""
    parsed = urlparse(_ensure_url_has_scheme(url))
    host = (parsed.hostname or "").strip(".").lower()
    if not host:
        return False
    labels = [x for x in host.split(".") if x]
    return "live" in labels

def is_live_url(url: str) -> bool:
    """判断是否为直播类型链接或“跳转到直播”的重定向链接。

    规则：
    - 直链：hostname 的任意标签为 live，则判定为直播域名链接
    - 重定向：若URL的 query 参数里包含一个可解码出的URL，且该URL为直播域名链接，则也判定为直播

    例：
    - https://live.bilibili.com/ -> True
    - https://api.live.bilibili.com/ -> True
    - https://example.com/redirect?url=https%3A%2F%2Flive.example.com%2Froom -> True
    - https://www.douyin.com/ -> False
    """
    if not url:
        return False
    try:
        if _is_live_url_basic(url):
            return True

        parsed = urlparse(_ensure_url_has_scheme(url))
        qs = parse_qs(parsed.query, keep_blank_values=True)
        for values in qs.values():
            for v in values:
                if not v:
                    continue
                candidate = v.strip()
                for _ in range(3):
                    if _is_live_url_basic(candidate):
                        return True
                    new_candidate = unquote(candidate)
                    if new_candidate == candidate:
                        break
                    candidate = new_candidate

        return False
    except Exception:
        return False

def build_request_headers(
    is_video: bool = False,
    referer: str = None,
    default_referer: str = None,
    origin: str = None,
    user_agent: str = None,
    custom_headers: dict = None
) -> dict:
    """构建请求头

    Args:
        is_video: 是否为视频（True为视频，False为图片）
        referer: Referer URL，如果提供则使用
        default_referer: 默认Referer URL（如果referer未提供）
        origin: Origin URL（可选）
        user_agent: User-Agent（可选，默认使用桌面端 User-Agent）
        custom_headers: 自定义请求头（如果提供，会与默认请求头合并）

    Returns:
        请求头字典
    """
    if custom_headers and 'Referer' in custom_headers:
        referer_url = custom_headers['Referer']
    else:
        referer_url = referer if referer else (default_referer or '')
    
    if user_agent:
        effective_user_agent = user_agent
    else:
        effective_user_agent = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    
    default_accept_language = 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7'
    
    if is_video:
        headers = {
            'User-Agent': effective_user_agent,
            'Accept': '*/*',
            'Accept-Language': default_accept_language,
            'Accept-Encoding': 'gzip, deflate',
        }
    else:
        headers = {
            'User-Agent': effective_user_agent,
            'Accept': (
                'image/avif,image/webp,image/apng,image/svg+xml,'
                'image/*,*/*;q=0.8'
            ),
            'Accept-Language': default_accept_language,
            'Accept-Encoding': 'gzip, deflate',
        }
    
    if referer_url:
        headers['Referer'] = referer_url
    
    if origin:
        headers['Origin'] = origin
    
    if custom_headers:
        headers.update(custom_headers)
    
    return headers
