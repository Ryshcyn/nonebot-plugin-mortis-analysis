"""Resolve Bilibili shares without fetching their destination web pages."""
from urllib.parse import urljoin, urlparse

import httpx


HOSTS = {'b23.tv', 'bili2233.cn', 'bilibili.com', 'www.bilibili.com',
         'space.bilibili.com', 'live.bilibili.com', 't.bilibili.com'}


async def resolve_short_url(url, headers=None):
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers=headers) as client:
        for _ in range(6):
            parsed = urlparse(url)
            if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in HOSTS
                    or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
                raise ValueError('B站短链跳转到了不支持的地址')
            # The API needs the destination URL, not a successful HTML response.
            # Bilibili can return HTTP 412 for HTML while its API still works.
            if parsed.hostname not in {'b23.tv', 'bili2233.cn'}:
                return url
            response = await client.get(url)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get('location')
                if not location:
                    raise ValueError('B站短链未返回跳转地址')
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            raise ValueError('B站短链未返回作品地址')
    raise ValueError('B站短链跳转次数过多')
