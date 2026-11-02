"""Platform-themed information cards, with no browser-side network requests."""
import asyncio
import base64
import io
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import aiohttp
from PIL import Image
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from nonebot_plugin_htmlrender import html_to_pic

ROOT = Path(__file__).resolve().parent
THEMES = {
    'bilibili': dict(label='哔哩哔哩 · 蓝粉', base='#14212f', text='#f0f5fa', muted='#a4b5c7', accent='#fb78ae', edge='#ffffff26', panel='#ffffff07', glow1='#256ca34a', glow2='#a1366b38'),
    'douyin': dict(label='抖音 · 红青', base='#15161d', text='#f0f1f5', muted='#a3a7b1', accent='#fe2c55', edge='#ffffff26', panel='#ffffff08', glow1='#9e244a50', glow2='#1b9d9b40'),
    'xiaohongshu': dict(label='小红书 · 红白', base='#fff9f9', text='#292125', muted='#796970', accent='#ed3151', edge='#af6a7b30', panel='#ffffff88', glow1='#ffdbdf7a', glow2='#ffe5e950'),
}
PATHS = {
    'platform': '<path d="m7 2 3 4m10-4-3 4M4 7h20a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z"/><path d="M8 12v4m12-4v4m-9 3h6"/>',
    'heart': '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
    'comment': '<path d="M21 11a8 8 0 0 1-8 8H8l-5 3 1-6a8 8 0 0 1-1-5 9 9 0 0 1 18 0Z"/><path d="M8 10h8m-8 4h5"/>',
    'star': '<path d="m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1Z"/>',
    'share': '<path d="m14 3 8 7-8 7v-5C7 12 4 15 2 20c0-9 4-13 12-13Z"/>',
}
ICONS = {key: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+('28 26' if key=='platform' else '24 24')+'" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+path+'</svg>' for key, path in PATHS.items()}

PLATFORM_NAMES = {'bilibili':'哔哩哔哩', 'douyin':'抖音', 'xiaohongshu':'小红书'}
REFERERS = {'bilibili':'https://www.bilibili.com/', 'douyin':'https://www.douyin.com/', 'xiaohongshu':'https://www.xiaohongshu.com/'}
ASSET_DOMAINS = ('hdslb.com','biliimg.com','douyinpic.com','byteimg.com','douyincdn.com','xhscdn.com','xiaohongshu.com','pstatp.com','snssdk.com','ibytedtos.com','bytegoofy.com')
RENDER_LIMIT = asyncio.Semaphore(2)

def number(value):
    if value is None:
        return '—'
    try:
        value = max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return '—'
    if value >= 100000000:
        return f'{value/100000000:.1f}'.rstrip('0').rstrip('.')+'亿'
    if value >= 10000:
        return f'{value/10000:.1f}'.rstrip('0').rstrip('.')+'万'
    return str(value)

def date(value):
    if not value:
        return ''
    try:
        number_value = float(value)
        if number_value > 10**12:
            number_value /= 1000
        return datetime.fromtimestamp(number_value, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError, OSError, OverflowError):
        return str(value)[:40]

def image_data(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image.seek(0)
        image.thumbnail((1400, 1400))
        output = io.BytesIO()
        image.convert('RGB').save(output, format='JPEG', quality=90)
    return 'data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode()

async def prepare(data):
    data = dict(data)
    platform = data.get('platform', 'bilibili')
    cache = {}
    semaphore = asyncio.Semaphore(6)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8), headers={
        'User-Agent':'Mozilla/5.0', 'Referer':REFERERS.get(platform, 'https://www.bilibili.com/')
    }) as session:
        async def fetch(value):
            if isinstance(value, bytes):
                try:
                    return await asyncio.to_thread(image_data, value)
                except Exception:
                    return ''
            candidates = value if isinstance(value, list) else [value]
            for url in candidates[:3]:
                if not isinstance(url, str):
                    continue
                parsed = urlparse(url)
                host = (parsed.hostname or '').lower()
                if parsed.scheme not in {'http','https'} or not any(host == d or host.endswith('.'+d) for d in ASSET_DOMAINS):
                    continue
                try:
                    async with semaphore:
                        # Do not forward platform cookies to media hosts or redirects.
                        async with session.get(url.replace('http:','https:',1), allow_redirects=False) as response:
                            response.raise_for_status()
                            if response.status != 200:
                                continue
                            raw = bytearray()
                            async for chunk in response.content.iter_chunked(65536):
                                raw.extend(chunk)
                                if len(raw) > 8*1024*1024:
                                    raise ValueError('Image too large')
                            return await asyncio.to_thread(image_data, bytes(raw))
                except Exception:
                    continue
            return ''
        async def asset(value):
            key = str(value)
            if key not in cache:
                cache[key] = asyncio.create_task(fetch(value))
            return await cache[key]
        async def comment(item):
            item = dict(item)
            avatar_candidates = item.get('avatar_urls') or item.get('avatar', '')
            item['avatar_data'] = await asset(avatar_candidates)
            item['date'] = date(item.get('timestamp')) or str(item.get('time') or '')
            item['likes'] = number(item.get('like'))
            item['is_author'] = bool(item.get('is_author') or item.get('is_up'))
            content = str(item.get('raw_content', item.get('content') or item.get('message') or ''))
            emotes = {}
            for token, url in (item.get('emote_map') or {}).items():
                encoded = await asset(url)
                if encoded:
                    emotes[token] = encoded
            if emotes:
                tokens = re.split('('+'|'.join(re.escape(t) for t in sorted(emotes,key=len,reverse=True))+')', content)
                item['content_html'] = Markup('').join(Markup('<img class="emote" src="{}" alt="{}">').format(emotes[t],t) if t in emotes else escape(t) for t in tokens)
            else:
                item['content_html'] = escape(content)
            item['image_data'] = [encoded for encoded in await asyncio.gather(*(asset(u) for u in (item.get('images') or [])[:3])) if encoded]
            item['replies'] = await asyncio.gather(*(comment(r) for r in (item.get('replies') or [])[:2]))
            return item
        cover, avatar, comments = await asyncio.gather(asset(data.get('cover')), asset(data.get('avatar')), asyncio.gather(*(comment(c) for c in data.get('comments', []))))
    return data, cover, avatar, comments

async def render_card(data):
    async with RENDER_LIMIT:
        data, cover, avatar, comments = await prepare(data)
        platform = data.get('platform', 'bilibili')
        theme = THEMES.get(platform, THEMES['douyin'])
        stats = data.get('stats') or {}
        metrics = [dict(icon=i,label=l,value=number(stats.get(k))) for i,l,k in [('heart','点赞','like'),('comment','评论','reply'),('star','收藏','favorite'),('share','转发','share')]]
        seconds = max(0, int(data.get('duration') or 0))
        description = str(data.get('desc') or '').strip()
        data.setdefault('comments', [])
        data.setdefault('brand', '小睦解析')
        data.setdefault('fetched_at', datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M'))
        data.setdefault('show_comments', True)
        env = Environment(loader=FileSystemLoader(ROOT), autoescape=select_autoescape(['html']))
        html = env.get_template('card.html').render(
            data=data, theme=theme, theme_note='', icons=ICONS, comments=comments,
            platform_name=PLATFORM_NAMES.get(platform, platform), cover=cover, avatar=avatar,
            metrics=metrics, duration=f'{seconds//60:02d}:{seconds%60:02d}',
            published=date(data.get('timestamp')), description='' if description in ('','-') else description,
            views=number(stats.get('view')), coins=number(stats.get('coin')), danmaku=number(stats.get('danmaku')))
        return await html_to_pic(html=html, viewport={'width':760, 'height':1000})

