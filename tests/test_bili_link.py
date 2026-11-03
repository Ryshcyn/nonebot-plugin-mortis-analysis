import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

SPEC = importlib.util.spec_from_file_location(
    'bili_link', Path(__file__).resolve().parents[1] /
    'nonebot_plugin_mortis_analysis/core/bili_link.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BilibiliShortLinkTests(unittest.IsolatedAsyncioTestCase):
    async def resolve(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(MODULE.httpx, 'AsyncClient', return_value=client):
            return await MODULE.resolve_short_url('https://b23.tv/example')

    async def test_destination_is_returned_without_requesting_blocked_html(self):
        calls = []
        destination = 'https://www.bilibili.com/video/BV1H6xe6PEdU?p=2&share_source=QQ'

        def handler(request):
            calls.append(str(request.url))
            if request.url.host == 'b23.tv':
                return httpx.Response(302, headers={'Location': destination})
            return httpx.Response(412)

        self.assertEqual(await self.resolve(handler), destination)
        self.assertEqual(calls, ['https://b23.tv/example'])

    async def test_relative_redirect_and_second_short_domain(self):
        targets = {'/example': '/next', '/next': 'https://bili2233.cn/final'}

        def handler(request):
            target = (targets[request.url.path] if request.url.host == 'b23.tv'
                      else 'https://t.bilibili.com/123?from=share')
            return httpx.Response(302, headers={'Location': target})

        self.assertEqual(await self.resolve(handler), 'https://t.bilibili.com/123?from=share')

    async def test_real_short_link_http_failure_remains_an_error(self):
        with self.assertRaises(httpx.HTTPStatusError) as error:
            await self.resolve(lambda request: httpx.Response(503))
        self.assertEqual(error.exception.response.status_code, 503)

    async def test_external_redirect_is_not_fetched(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={'Location': 'https://example.com/video'})

        with self.assertRaises(ValueError):
            await self.resolve(handler)
        self.assertEqual(len(calls), 1)

    async def test_missing_location_and_redirect_loop_fail(self):
        for headers in [{}, {'Location': '/example'}]:
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                await self.resolve(lambda request: httpx.Response(302, headers=headers))


if __name__ == '__main__':
    unittest.main()
