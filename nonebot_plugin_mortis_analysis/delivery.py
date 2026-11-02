"""Ordered long-card and media delivery shared by platform handlers."""
import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from bilibili_api import video, Credential
from bilibili_api.opus import Opus
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageSegment

from .card import render_card
from .settings import get_store
from .video_limits import VideoLimitExceeded, maximum_bytes, check_size, check_metadata, send_limit_notice
from .share_links import extract_message_links
from .opus import parse_opus_content


async def handle_bilibili_opus(bot, event, url):
    """读取动态并发送全部正文与图片，为失败和超时返回明确提示。"""
    from . import send_both, send_forward_both, make_node_segment
    from urllib.parse import urlparse
    import re
    match = re.search(r'/(?:opus/)?(\d+)(?:/)?$', urlparse(url).path)
    if not match:
        await send_both(bot, event, MessageSegment.text('无法识别这条 B站动态链接，请重新分享原链接。'))
        return
    try:
        value = get_store().current()['bili_sessdata']
        info = await asyncio.wait_for(Opus(int(match.group(1)), Credential(sessdata=value or None)).get_info(), timeout=20)
        title, text, pictures = parse_opus_content(info)
    except asyncio.TimeoutError:
        await send_both(bot, event, MessageSegment.text('B站动态读取超时，请稍后重试。'))
        return
    except Exception as exc:
        logger.warning(f'[小睦解析] B站动态读取失败：{type(exc).__name__}')
        await send_both(bot, event, MessageSegment.text('B站动态暂时无法读取，请检查链接及登录凭据后重试。'))
        return
    if not text and not pictures:
        await send_both(bot, event, MessageSegment.text(f'{title}\n这条动态暂无可发送的正文或图片，请打开原链接查看。'))
        return
    nickname = get_store().current()['nickname']
    await send_both(bot, event, MessageSegment.text(f'{nickname}识别：B站动态，{title}'+('\n'+text if text else '')))
    if pictures:
        nodes = [make_node_segment(bot.self_id, MessageSegment.image(url)) for url in pictures]
        await send_forward_both(bot, event, nodes)


def comment_state(event):
    from . import get_id_both, comment_shutdown_list_in_memory, comment_mode_map_in_memory
    sender = get_id_both(event)
    count = get_store().current()['hot_comment_count']
    return bool(count and sender not in comment_shutdown_list_in_memory), comment_mode_map_in_memory.get(str(sender), 'image')


async def send_information(bot, event, data, comments, bili=False):
    from . import send_both, send_forward_both, get_id_both, resolve_shutdown_list_in_memory
    from .core.comment import format_bili_comments_to_nodes, format_comments_to_nodes
    enabled, mode = comment_state(event)
    if get_id_both(event) in resolve_shutdown_list_in_memory:
        return False
    settings = get_store().current()
    data = dict(data, brand=settings['nickname'], comments=comments if enabled and mode == 'image' else [], show_comments=enabled and mode == 'image')
    try:
        image = await render_card(data)
    except Exception as exc:
        logger.warning(f'[小睦解析] 长图渲染失败：{type(exc).__name__}')
        # The original metadata remains readable even if Chromium is unavailable.
        lines = [data.get('title'), data.get('author'), data.get('desc')]
        await send_both(bot, event, MessageSegment.text('\n'.join(str(x) for x in lines if x)))
        if enabled:
            mode = 'text'
    else:
        await send_both(bot, event, MessageSegment.image(image))
    if enabled and mode == 'text' and comments:
        formatter = format_bili_comments_to_nodes if bili else format_comments_to_nodes
        try:
            await send_forward_both(bot, event, formatter(bot.self_id, comments, data.get('title', ''), settings['nickname']))
        except Exception as exc:
            logger.warning(f'[小睦解析] 评论发送失败：{type(exc).__name__}')
    return True


async def send_local_video(bot, event, path):
    from . import send_both, get_id_both, resolve_shutdown_list_in_memory
    from .video_processing import probe
    if get_id_both(event) in resolve_shutdown_list_in_memory:
        return
    check_size(Path(path).stat().st_size, maximum_bytes())
    duration, _ = await probe(path)
    check_metadata(duration)
    await send_both(bot, event, MessageSegment.video(f'file://{path}'), timeout=300)


async def handle_bilibili_video(bot, event, url):
    from . import send_both
    from .core.common import CACHE_DIR
    from .core.bili23 import download_b_file
    from .core.comment import get_bilibili_comments
    import aiohttp

    settings = get_store().current()
    paths = []
    information_sent = False
    try:
        import re
        matched = re.search(r'BV[0-9A-Za-z]{10}', url)
        if not matched:
            raise ValueError('Video ID missing')
        bvid = matched.group()
        v = video.Video(bvid=bvid, credential=Credential(sessdata=settings['bili_sessdata'] or None))
        info = await asyncio.wait_for(v.get_info(), timeout=20)
        page = int(parse_qs(urlparse(url).query).get('p', ['1'])[0])-1
        if page < 0 or page >= len(info.get('pages') or [None]):
            raise ValueError('Invalid page')
        duration = (info.get('pages') or [{}])[page].get('duration', info.get('duration', 0))
        comments = []
        if comment_state(event)[0]:
            async with aiohttp.ClientSession() as session:
                try:
                    comments = await asyncio.wait_for(get_bilibili_comments(session, info['aid'], settings['bili_sessdata'], bvid, info.get('owner', {}).get('mid')), timeout=12)
                except Exception as exc:
                    logger.warning(f'[小睦解析] B站评论暂不可用，继续发送作品：{type(exc).__name__}')
                    comments = []
                comments = comments[:settings['hot_comment_count']]
        owner = info.get('owner') or {}
        data = dict(platform='bilibili', bvid=bvid, title=info['title'], cover=info.get('pic'),
                    avatar=owner.get('face'), author=owner.get('name', ''), timestamp=info.get('pubdate'),
                    duration=duration, desc=info.get('desc', ''), stats=info.get('stat', {}))
        if not await send_information(bot, event, data, comments, bili=True):
            return
        information_sent = True
        check_metadata(duration)
        streams = await asyncio.wait_for(v.get_download_url(page_index=page, html5=True), timeout=20)
        base = CACHE_DIR/uuid4().hex
        result = str(base)+'.mp4'
        paths.append(result)
        dash = streams.get('dash') or {}
        if dash.get('video') and dash.get('audio'):
            compatible = [s for s in dash['video'] if str(s.get('codecs', '')).startswith('avc')]
            candidates = compatible or dash['video']
            stream = min(candidates, key=lambda s: abs(s.get('height', 720)-720))
            audio = dash['audio'][0]
            vp, ap = str(base)+'.video.m4s', str(base)+'.audio.m4s'
            paths.extend([vp, ap])
            await download_b_file(stream.get('baseUrl') or stream['base_url'], vp, lambda _: None, max_bytes=maximum_bytes())
            await download_b_file(audio.get('baseUrl') or audio['base_url'], ap, lambda _: None,
                                  max_bytes=max(0, maximum_bytes()-Path(vp).stat().st_size))
            from .video_processing import run_process
            await run_process('ffmpeg', '-v', 'error', '-y', '-i', vp, '-i', ap,
                '-c', 'copy', '-movflags', '+faststart', result, timeout=120)
        else:
            segments = streams.get('durl') or []
            if len(segments) != 1:
                raise RuntimeError('Unsupported segmented video')
            await download_b_file(segments[0]['url'], result, lambda _: None)
        await send_local_video(bot, event, result)
    except VideoLimitExceeded as exc:
        await send_limit_notice(bot, event, exc)
    except Exception as exc:
        logger.warning(f'[小睦解析] B站解析失败：{type(exc).__name__}')
        message = '作品信息已解析，但视频处理或发送未完成，请稍后重试。' if information_sent else '视频解析失败，请检查链接是否有效及平台登录凭据。'
        await send_both(bot, event, MessageSegment.text(message))
    finally:
        for path in paths:
            Path(path).unlink(missing_ok=True)


async def handle_public_share(bot, event, parser):
    import aiohttp
    from . import send_both, send_forward_both, make_node_segment, get_id_both, resolve_shutdown_list_in_memory
    from .core.common import download_img, download_video, download_audio, SkipParse
    links = extract_message_links(parser, event.message)
    if not links:
        return
    paths = []
    information_sent = False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            metadata = await parser.parse(session, links[0])
            if not metadata:
                raise RuntimeError('No public media')
            def first(value):
                while isinstance(value, list):
                    value = value[0] if value else ''
                return value or ''
            comments = [dict(c, content=c.get('message', c.get('content', '')), like=c.get('likes', c.get('like', 0)))
                        for c in metadata.get('hot_comments', [])]
            cover = first(metadata.get('video_cover_urls')) or metadata.get('cover') or first(metadata.get('image_urls'))
            data = dict(metadata, platform=parser.name, cover=cover)
            if not await send_information(bot, event, data, comments):
                return
            information_sent = True
            failures = {'image': 0, 'video': 0, 'audio': 0}
            image_nodes = []
            for kind in ('image', 'video', 'audio'):
                if kind == 'video' and metadata.get('video_urls'):
                    check_metadata(metadata.get('duration'))
                for group in metadata.get(kind+'_urls', []):
                    if get_id_both(event) in resolve_shutdown_list_in_memory:
                        return
                    candidates = group if isinstance(group, list) else [group]
                    path = None
                    rejected = False
                    for url in dict.fromkeys(u for u in candidates if isinstance(u, str) and u):
                        try:
                            if kind == 'image':
                                path = await download_img(url, session=session, headers=metadata.get('image_headers'))
                            elif kind == 'video':
                                path = await download_video(url, ext_headers=metadata.get('video_headers'))
                            else:
                                path = await download_audio(url, headers=metadata.get('audio_headers'))
                            if path:
                                paths.append(path)
                            if not path or not Path(path).is_file() or not Path(path).stat().st_size:
                                raise RuntimeError('Empty media')
                            break
                        except VideoLimitExceeded as exc:
                            await send_limit_notice(bot, event, exc)
                            path = None
                            rejected = True
                            break
                        except Exception as exc:
                            path = None
                            logger.warning(f'[小睦解析] {kind} 下载地址不可用，尝试备用地址：{type(exc).__name__}')
                    if not path:
                        if not rejected:
                            failures[kind] += 1
                        continue
                    try:
                        if kind == 'image':
                            image_nodes.append(make_node_segment(bot.self_id, MessageSegment.image(f'file://{path}')))
                        elif kind == 'video':
                            await send_local_video(bot, event, path)
                        else:
                            await send_both(bot, event, MessageSegment.record(f'file://{path}'))
                    except VideoLimitExceeded as exc:
                        await send_limit_notice(bot, event, exc)
                    except Exception as exc:
                        failures[kind] += 1
                        logger.warning(f'[小睦解析] {kind} 发送失败：{type(exc).__name__}')
                if kind == 'image' and image_nodes:
                    if get_id_both(event) in resolve_shutdown_list_in_memory:
                        return
                    try:
                        await send_forward_both(bot, event, image_nodes)
                    except Exception as exc:
                        failures['image'] += len(image_nodes)
                        logger.warning(f'[小睦解析] 图片合并转发失败：{type(exc).__name__}')
            missing = [f'{count} {label}' for kind, label in [('image', '张图片'), ('video', '段视频'), ('audio', '段音频')]
                       if (count := failures[kind])]
            if missing:
                await send_both(bot, event, MessageSegment.text('作品信息已解析，但有 '+ '、'.join(missing) +'未能下载或发送，其余可用内容已发送。'))
    except SkipParse:
        return
    except VideoLimitExceeded as exc:
        await send_limit_notice(bot, event, exc)
    except PermissionError:
        await send_both(bot, event, MessageSegment.text('该平台要求登录或验证码，当前凭据无法读取这条分享。'))
    except Exception as exc:
        logger.warning(f'[小睦解析] 分享处理失败：{type(exc).__name__}')
        message = '作品信息已解析，但后续媒体处理未完成。' if information_sent else '分享解析失败，请检查链接和平台登录凭据。'
        await send_both(bot, event, MessageSegment.text(message))
    finally:
        for path in paths:
            Path(path).unlink(missing_ok=True)
