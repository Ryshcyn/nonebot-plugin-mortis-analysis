import re
from uuid import uuid4
import json
import asyncio
import aiohttp
import os.path
from functools import wraps
from typing import Iterable, Union
from urllib.parse import parse_qs

from bilibili_api import video, Credential, live, article
from bilibili_api.favorite_list import get_video_favorite_list_content
from bilibili_api.video import VideoDownloadURLDataDetecter
from nonebot import on_regex, get_driver, on_command
from nonebot.adapters.onebot.v11 import Message, Event, Bot, MessageSegment, GROUP_ADMIN, GROUP_OWNER
from nonebot.adapters.onebot.v11.event import GroupMessageEvent, PrivateMessageEvent
from nonebot.matcher import current_bot
from nonebot.exception import MatcherException
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me

from nonebot import require
require('nonebot_plugin_htmlrender')
require('nonebot_plugin_localstore')
from .config import Config
from .core.network import request as async_http_request
from .video_limits import VideoLimitExceeded, send_limit_notice
# noinspection PyUnresolvedReferences
from .constants import COMMON_HEADER, XHS_REQ_LINK, \
    BILIBILI_HEADER, NETEASE_API_CN, NETEASE_TEMP_API, NETEASE_TEMP_API_FALLBACK, VIDEO_MAX_MB
from .core.bili23 import download_b_file, merge_file_to_mp4, extra_bili_info
from .core.common import *
from .core.douyin.parser import DouyinParser
from .core.xiaohongshu import XiaohongshuParser
from .core.common import (
    load_or_initialize_comment_list,
    save_comment_list,
    load_comment_mode_map,
    save_comment_mode_map
)





__plugin_meta__ = PluginMetadata(
    name="小睦解析",
    description="解析视频与图文分享，生成平台主题信息长图和热门评论，并顺序发送媒体。",
    usage="发送视频或图文分享链接；群管理可 @机器人 开启解析/关闭解析、开启评论/关闭评论、切换评论模式。",
    type="application",
    homepage="https://github.com/Ryshcyn/nonebot-plugin-mortis-analysis",
    config=Config,
    supported_adapters={ "~onebot.v11" }
)

# 配置加载
from nonebot import get_plugin_config
global_config = get_plugin_config(Config)
from .settings import initialize, get_store
from pathlib import Path
initialize({
    'enabled': global_config.mortis_analysis_enabled,
    'nickname': global_config.mortis_analysis_nickname or global_config.r_global_nickname or '小睦解析',
    'hot_comment_count': global_config.mortis_analysis_hot_comment_count,
    'video_max_duration': global_config.mortis_analysis_video_max_duration,
    'video_max_size_mb': global_config.mortis_analysis_video_max_size_mb,
    'blocked_platforms': [x.strip() for x in (global_config.global_resolve_controller or '').split(',') if x.strip()],
    'bili_sessdata': (global_config.bili_sessdata if global_config.mortis_analysis_bili_sessdata is None else global_config.mortis_analysis_bili_sessdata) or '',
    'xhs_ck': (global_config.xhs_ck if global_config.mortis_analysis_xhs_ck is None else global_config.mortis_analysis_xhs_ck) or '',
})

def refresh_runtime():
    global GLOBAL_NICKNAME, BILI_SESSDATA, credential
    values = get_store().current()
    GLOBAL_NICKNAME = values['nickname']
    BILI_SESSDATA = values['bili_sessdata']
    credential = Credential(sessdata=BILI_SESSDATA or None)
    return values

# 全局名称
GLOBAL_NICKNAME: str = str(getattr(global_config, "r_global_nickname", ""))
# 全局解析内容控制
GLOBAL_RESOLVE_CONTROLLER: list = split_and_strip(str(getattr(global_config, "global_resolve_controller", "[]")), ",")
# 哔哩哔哩的 SESSDATA
BILI_SESSDATA: str = str(getattr(global_config, "bili_sessdata", ""))
# 构建哔哩哔哩的Credential
credential = Credential(sessdata=BILI_SESSDATA)

bili23 = on_regex(
    r"(bilibili.com|b23.tv|bili2233.cn|^BV[0-9a-zA-Z]{10}$)", priority=1
)
# 匹配抖音短链、分享页、视频和图集链接。
douyin = on_regex(
    r"(v\.douyin\.com|iesdouyin\.com|douyin\.com\/(video|note|slides))",
    priority=1,
    block=True
)
xhs = on_regex(
    r"(xhslink\.(?:com|cn)|xiaohongshu\.com)", priority=1
)
ncm = on_regex(
    r"(music.163.com|163cn.tv)"
)

enable_resolve = on_command('开启解析', rule=to_me(), permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
disable_resolve = on_command('关闭解析', rule=to_me(), permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
check_resolve = on_command('查看关闭解析', permission=SUPERUSER)
# 注册评论控制指令
enable_comment = on_command('开启评论', rule=to_me(), permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
disable_comment = on_command('关闭评论', rule=to_me(), permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
switch_comment_mode = on_command('切换评论模式', rule=to_me(), permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
reload_comment_template = on_command('重载评论模板', permission=SUPERUSER)
# 内存中关闭解析的名单，第一次先进行初始化
resolve_shutdown_list_in_memory: list = load_or_initialize_list()
# 在内存中初始化评论控制名单
comment_shutdown_list_in_memory: list = load_or_initialize_comment_list()
comment_mode_map_in_memory: dict = load_comment_mode_map()


def resolve_handler(func):
    """
    解析控制装饰器
    :param func:
    :return:
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 假设 `event` 是通过被装饰函数的参数传入的
        event = kwargs.get('event') or args[1]  # 根据位置参数或者关键字参数获取 event
        send_id = get_id_both(event)

        settings = refresh_runtime()
        if settings['enabled'] and send_id not in resolve_shutdown_list_in_memory:
            return await func(*args, **kwargs)
        else:
            logger.info(f"发送者/群 {send_id} 已关闭解析，不再执行")
            return None

    return wrapper


@enable_resolve.handle()
async def enable(bot: Bot, event: Event):
    """
    开启解析
    :param bot:
    :param event:
    :return:
    """
    send_id = get_id_both(event)
    if send_id in resolve_shutdown_list_in_memory:
        resolve_shutdown_list_in_memory.remove(send_id)
        await asyncio.to_thread(save_sub_user, resolve_shutdown_list_in_memory)
        logger.info(resolve_shutdown_list_in_memory)
        await enable_resolve.finish('解析已开启')
    else:
        await enable_resolve.finish('解析已开启，无需重复开启')


@disable_resolve.handle()
async def disable(bot: Bot, event: Event):
    """
    关闭解析
    :param bot:
    :param event:
    :return:
    """
    send_id = get_id_both(event)
    if send_id not in resolve_shutdown_list_in_memory:
        resolve_shutdown_list_in_memory.append(send_id)
        await asyncio.to_thread(save_sub_user, resolve_shutdown_list_in_memory)
        logger.info(resolve_shutdown_list_in_memory)
        await disable_resolve.finish('解析已关闭')
    else:
        await disable_resolve.finish('解析已关闭，无需重复关闭')


@check_resolve.handle()
async def check_disable(bot: Bot, event: Event):
    """
    查看关闭解析
    :param bot:
    :param event:
    :return:
    """
    memory_disable_list = [str(item) + "--" + (await bot.get_group_info(group_id=item))['group_name'] for item in
                           resolve_shutdown_list_in_memory]
    memory_disable_list = "1. 在【内存】中的名单有：\n" + '\n'.join(memory_disable_list)
    persistence_disable_list = [str(item) + "--" + (await bot.get_group_info(group_id=item))['group_name'] for item in
                                list(await asyncio.to_thread(load_sub_user))]
    persistence_disable_list = "2. 在【持久层】中的名单有：\n" + '\n'.join(persistence_disable_list)

    await check_resolve.send(Message("已经发送到私信了~"))
    await bot.send_private_msg(user_id=event.user_id, message=Message(
        "[nonebot_plugin_mortis_analysis 关闭名单如下：]" + "\n\n" + memory_disable_list + '\n\n' + persistence_disable_list + "\n\n" + "🌟 温馨提示：如果想关闭解析需要艾特我然后输入: 关闭解析"))

@enable_comment.handle()
async def enable_cmt(bot: Bot, event: Event):
    send_id = get_id_both(event)
    if send_id in comment_shutdown_list_in_memory:
        comment_shutdown_list_in_memory.remove(send_id)
        await asyncio.to_thread(save_comment_list, comment_shutdown_list_in_memory)
        await enable_comment.finish('评论已开启')
    else:
        await enable_comment.finish('评论已开启，无需重复开启')


@disable_comment.handle()
async def disable_cmt(bot: Bot, event: Event):
    send_id = get_id_both(event)
    if send_id not in comment_shutdown_list_in_memory:
        comment_shutdown_list_in_memory.append(send_id)
        await asyncio.to_thread(save_comment_list, comment_shutdown_list_in_memory)
        await disable_comment.finish('评论已关闭')
    else:
        await disable_comment.finish('评论已关闭，无需重复关闭')


@switch_comment_mode.handle()
async def switch_cmt_mode(bot: Bot, event: Event):
    send_id = str(get_id_both(event))
    current_mode = comment_mode_map_in_memory.get(send_id, 'image')
    new_mode = 'text' if current_mode == 'image' else 'image'

    comment_mode_map_in_memory[send_id] = new_mode
    await asyncio.to_thread(save_comment_mode_map, comment_mode_map_in_memory)

    mode_name = "【文字合并转发】" if new_mode == 'text' else "【HTML图片渲染】"
    await switch_comment_mode.finish(f'已切换至 {mode_name} 评论模式')


@reload_comment_template.handle()
async def reload_tpl(bot: Bot, event: Event):
    try:
        from .core.comment import load_template, load_bili_template
        await asyncio.to_thread(load_template, force_reload=True)
        await asyncio.to_thread(load_bili_template, force_reload=True)  # 强制重载 B站评论模板。
    except Exception as e:
        await reload_comment_template.finish(f'模板重载失败: {e}')
    await reload_comment_template.finish('评论 HTML 模板重载成功！')

def resolve_controller(func):
    """
        将装饰器应用于函数，通过装饰器自动判断是否允许执行函数
    :param func:
    :return:
    """

    logger.debug(
        f"[nonebot_plugin_mortis_analysis][解析全局控制] 加载 {func.__name__} {'禁止' if func.__name__ in GLOBAL_RESOLVE_CONTROLLER else '允许'}")

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 判断函数名是否在允许列表中
        if func.__name__ not in get_store().current()['blocked_platforms']:
            logger.info(f"[nonebot_plugin_mortis_analysis][解析全局控制] {func.__name__}...")
            from inspect import signature
            arguments = signature(func).bind_partial(*args, **kwargs).arguments
            event = arguments.get('event')
            bot = arguments.get('bot') or current_bot.get()
            if event is not None:
                try:
                    notice = global_config.mortis_analysis_parse_notice.strip()
                    if notice:
                        message = MessageSegment.reply(event.message_id) + MessageSegment.text(notice)
                        await send_both(bot, event, message)
                except Exception as exc:
                    logger.warning(f'[小睦解析] 解析提示发送失败：{type(exc).__name__}')
            try:
                return await func(*args, **kwargs)
            except VideoLimitExceeded as exc:
                await send_limit_notice(bot, event, exc)
            except MatcherException:
                raise
            except Exception as exc:
                logger.warning(f'[小睦解析] 解析未完成：{type(exc).__name__}')
                await send_both(bot, event, MessageSegment.text('解析暂时未能完成，请检查链接、平台凭据或稍后重试。'))
        else:
            logger.warning(f"[nonebot_plugin_mortis_analysis][解析全局控制] {func.__name__} 被禁止执行")
            return None

    return wrapper


@bili23.handle()
@resolve_handler
@resolve_controller
async def bilibili(bot: Bot, event: Event) -> None:
    """
        哔哩哔哩解析
    :param bot:
    :param event:
    :return:
    """
    from .share_links import extract_bilibili_link
    from urllib.parse import urlparse
    url = extract_bilibili_link(event.message)
    if not url:
        await send_both(bot, event, MessageSegment.text('未找到有效的 B站链接，请重新分享。'))
        return
    if urlparse(url).hostname in {'b23.tv', 'bili2233.cn'}:
        try:
            response = await async_http_request('GET', url, headers=BILIBILI_HEADER, follow_redirects=True)
            url = str(response.url)
        except Exception as exc:
            logger.warning(f'[小睦解析] B站短链读取失败：{type(exc).__name__}')
            await send_both(bot, event, MessageSegment.text('B站短链暂时无法读取，请使用完整链接或稍后重试。'))
            return
    parsed = urlparse(url)
    if parsed.hostname == 't.bilibili.com' or parsed.path.startswith('/opus/'):
        from .delivery import handle_bilibili_opus
        await handle_bilibili_opus(bot, event, url)
        return
    # 直播间识别
    if parsed.hostname == 'live.bilibili.com':
        # https://live.bilibili.com/30528999?hotRank=0
        match = re.fullmatch(r'/(\d+)/?', parsed.path)
        if not match:
            await send_both(bot, event, MessageSegment.text('未找到有效的 B站直播间编号。'))
            return
        room_id = match.group(1)
        room = live.LiveRoom(room_display_id=int(room_id))
        room_info = (await room.get_room_info())['room_info']
        title, cover, keyframe = room_info['title'], room_info['cover'], room_info['keyframe']
        await send_both(bot, event, Message([MessageSegment.image(cover), MessageSegment.image(keyframe),
                                   MessageSegment.text(f"{GLOBAL_NICKNAME}识别：哔哩哔哩直播，{title}")]))
        return
    # 专栏识别
    if parsed.path.startswith('/read/'):
        match = re.fullmatch(r'/read/cv(\d+)/?', parsed.path)
        if not match:
            await send_both(bot, event, MessageSegment.text('未找到有效的 B站专栏编号。'))
            return
        ar = article.Article(int(match.group(1)), credential=credential)
        # 如果专栏为公开笔记，则转换为笔记类
        # NOTE: 笔记类的函数与专栏类的函数基本一致
        if await ar.is_note():
            ar = ar.turn_to_note()
        # 加载内容
        await ar.fetch_content()
        markdown_path = str(CACHE_DIR / (uuid4().hex + '.md'))
        markdown = await asyncio.to_thread(ar.markdown)
        await asyncio.to_thread(Path(markdown_path).write_text, markdown, encoding='utf8')
        try:
            await send_both(bot, event, Message(f"{GLOBAL_NICKNAME}识别：哔哩哔哩专栏"))
            await upload_both(bot, event, markdown_path, f'专栏_{match.group(1)}.md')
        finally:
            await asyncio.to_thread(Path(markdown_path).unlink, missing_ok=True)
        return
    # 收藏夹识别
    if parsed.path.rstrip('/').endswith('/favlist'):
        # https://space.bilibili.com/22990202/favlist?fid=2344812202
        fav_id = parse_qs(parsed.query).get('fid', [''])[0]
        if not fav_id.isdigit():
            await send_both(bot, event, MessageSegment.text('收藏夹链接缺少有效的 fid，请重新分享。'))
            return
        fav_list = (await get_video_favorite_list_content(int(fav_id), credential=credential)).get('medias') or []
        fav_list = fav_list[:10]
        if not fav_list:
            await send_both(bot, event, MessageSegment.text('收藏夹暂无可读取的作品，请检查访问权限和登录凭据。'))
            return
        favs = []
        for fav in fav_list:
            title, cover, intro = fav.get('title', ''), fav.get('cover', ''), fav.get('intro', '')
            link = fav.get('link') or ('https://www.bilibili.com/video/'+fav['bvid'] if fav.get('bvid') else '')
            logger.info(title, cover, intro)
            favs.append(
                [MessageSegment.image(cover),
                 MessageSegment.text(f'🧉 标题：{title}\n📝 简介：{intro}\n🔗 链接：{link}')])
        await send_both(bot, event, MessageSegment.text(f'{GLOBAL_NICKNAME}识别：哔哩哔哩收藏夹'))
        await send_forward_both(bot, event, make_node_segment(bot.self_id, favs))
        return
    from .delivery import handle_bilibili_video
    await handle_bilibili_video(bot, event, url)




async def parse_public_share(bot: Bot, event: Event, parser) -> None:
    from .delivery import handle_public_share
    await handle_public_share(bot, event, parser)


@douyin.handle()
@resolve_handler
@resolve_controller
async def dy(bot: Bot, event: Event) -> None:
    await parse_public_share(bot, event, DouyinParser(hot_comment_count=get_store().current()['hot_comment_count']))








@xhs.handle()
@resolve_handler
@resolve_controller
async def xiaohongshu(bot: Bot, event: Event):
    await parse_public_share(bot, event, XiaohongshuParser(hot_comment_count=get_store().current()['hot_comment_count'], cookie=get_store().current()['xhs_ck']))




@ncm.handle()
@resolve_handler
@resolve_controller
async def netease(bot: Bot, event: Event):
    message = str(event.message)
    # 识别短链接
    if "163cn.tv" in message:
        try:
            short_url = re.search(r"(http:|https:)\/\/163cn\.tv\/([a-zA-Z0-9]+)", message).group(0)
            async with httpx.AsyncClient() as client:
                head_resp = await client.head(short_url, follow_redirects=True)
            message = str(head_resp.url)
        except Exception as e:
            logger.error(f"[NCM] 短链解析失败: {e}")
            await ncm.finish(Message(f"❌ {GLOBAL_NICKNAME}无法解析此网易云短链接。"))

    match = re.search(r"id=(\d+)", message)
    if not match:
        await ncm.finish(Message(f"❌ {GLOBAL_NICKNAME}未能在链接中找到歌曲 ID。"))

    ncm_id = match.group(1)
    logger.info(f"[NCM] 歌曲 ID: {ncm_id}")

    api_candidates = [
        ("main", NETEASE_TEMP_API.replace('{}', ncm_id)),
        ("fallback", NETEASE_TEMP_API_FALLBACK.replace('{}', ncm_id)),
    ]

    ncm_url = None
    ncm_cover = None
    ncm_singer = '未知歌手'
    ncm_title = f'网易云歌曲_{ncm_id}'
    last_error = None

    for api_name, api_url in api_candidates:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(api_url, headers=COMMON_HEADER)
            logger.debug(f"[NCM][{api_name}] 接口状态: {response.status_code} | 内容: {response.text}")

            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                logger.warning(f"[NCM][{api_name}] 接口状态异常: {response.status_code}")
                continue

            resp_json = response.json()

            if api_name == "main":
                if resp_json.get('code') != 0:
                    last_error = resp_json.get('message', '未知错误')
                    logger.warning(f"[NCM][{api_name}] 接口返回错误: {last_error}")
                    continue

                data_list = resp_json.get('data')
                if not isinstance(data_list, list) or not data_list:
                    last_error = '接口未返回有效歌曲数据'
                    logger.warning(f"[NCM][{api_name}] 接口未返回有效 data: {resp_json}")
                    continue

                song_data = data_list[0]
                singers = song_data.get('singers') or []
                singer_names = [
                    singer.get('name') for singer in singers
                    if isinstance(singer, dict) and singer.get('name')
                ]

                ncm_url = song_data.get('url')
                ncm_cover = song_data.get('picurl')
                ncm_singer = ' / '.join(singer_names) if singer_names else '未知歌手'
                ncm_title = song_data.get('name') or f'网易云歌曲_{ncm_id}'
            else:
                if resp_json.get('status') != 200:
                    last_error = resp_json.get('msg', '未知错误')
                    logger.warning(f"[NCM][{api_name}] 接口返回错误: {last_error}")
                    continue

                ncm_url = resp_json.get('url')
                ncm_cover = resp_json.get('pic')
                ncm_singer = resp_json.get('ar_name') or '未知歌手'
                ncm_title = resp_json.get('name') or f'网易云歌曲_{ncm_id}'

            if ncm_url:
                logger.info(f"[NCM] 使用 {api_name} 接口解析成功")
                break

            last_error = '未获取到播放链接'
            logger.warning(f"[NCM][{api_name}] 接口未返回播放链接: {resp_json}")
        except Exception as e:
            last_error = str(e)
            logger.error(f"[NCM][{api_name}] 接口请求失败: {e}")

    if not ncm_url:
        await ncm.finish(f"❌ 未获取到播放链接，主备接口均失败：{last_error or '未知错误'}")
        return

    await ncm.send(Message([
        MessageSegment.image(ncm_cover),
        MessageSegment.text(
            f'{GLOBAL_NICKNAME}开始识别\n来源：网易云音乐\n'
            f'歌名：{ncm_title} - {ncm_singer}'
        ),
    ]))

    ncm_music_path = None
    try:
        ncm_music_path = await download_audio(ncm_url)
        await ncm.send(Message(MessageSegment.record(ncm_music_path)))
        await upload_both(
            bot, event, ncm_music_path,
            f'{ncm_title}-{ncm_singer}.{ncm_music_path.split(".")[-1]}',
        )
    except Exception as e:
        logger.error(f"[NCM] 音频下载/发送失败: {e}")
        await ncm.send("❌ 音频下载或发送失败。")
    finally:
        if ncm_music_path and os.path.exists(ncm_music_path):
            os.unlink(ncm_music_path)








def make_node_segment(user_id, segments: Union[MessageSegment, List]) -> Union[
    MessageSegment, Iterable[MessageSegment]]:
    """
        将消息封装成 Segment 的 Node 类型，可以传入单个也可以传入多个，返回一个封装好的转发类型
    :param user_id: 可以通过event获取
    :param segments: 一般为 MessageSegment.image / MessageSegment.video / MessageSegment.text
    :return:
    """
    if isinstance(segments, list):
        return [MessageSegment.node_custom(user_id=user_id, nickname=GLOBAL_NICKNAME,
                                           content=Message(segment)) for segment in segments]
    return MessageSegment.node_custom(user_id=user_id, nickname=GLOBAL_NICKNAME,
                                      content=Message(segments))


async def send_forward_both(bot: Bot, event: Event, segments: Union[MessageSegment, List]) -> None:
    """
        自动判断message是 List 还是单个，然后发送{转发}，允许发送群和个人
    :param bot:
    :param event:
    :param segments:
    :return:
    """
    if isinstance(event, GroupMessageEvent):
        await bot.send_group_forward_msg(group_id=event.group_id,
                                         messages=segments)
    else:
        await bot.send_private_forward_msg(user_id=event.user_id,
                                           messages=segments)


async def send_both(bot: Bot, event: Event, segments: MessageSegment, *, timeout=None) -> None:
    """
        自动判断message是 List 还是单个，发送{单个消息}，允许发送群和个人
    :param bot:
    :param event:
    :param segments:
    :return:
    """
    options = {'_timeout': timeout} if timeout is not None else {}
    if isinstance(event, GroupMessageEvent):
        await bot.send_group_msg(group_id=event.group_id,
                                 message=Message(segments), **options)
    elif isinstance(event, PrivateMessageEvent):
        await bot.send_private_msg(user_id=event.user_id,
                                   message=Message(segments), **options)


async def upload_both(bot: Bot, event: Event, file_path: str, name: str) -> None:
    """
        上传文件，不限于群和个人
    :param bot:
    :param event:
    :param file_path:
    :param name:
    :return:
    """
    # 清理文件名中的非法字符，QQ 不允许文件名包含 \ / : * ? " < > |
    name = re.sub(r'[/\\]', '、', name)
    name = re.sub(r'[:*?"<>|]', '_', name)
    if isinstance(event, GroupMessageEvent):
        # 上传群文件
        await bot.upload_group_file(group_id=event.group_id, file=file_path, name=name)
    elif isinstance(event, PrivateMessageEvent):
        # 上传私聊文件
        await bot.upload_private_file(user_id=event.user_id, file=file_path, name=name)


def get_id_both(event: Event):
    if isinstance(event, GroupMessageEvent):
        return event.group_id
    elif isinstance(event, PrivateMessageEvent):
        return event.user_id


