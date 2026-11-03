"""Exercise message handlers without connecting a OneBot account."""
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        original = Path.cwd()
        try:
            os.chdir(cls.directory.name)
            nonebot.init(driver='~fastapi', _env_file=None, localstore_use_cwd=True, log_level='WARNING')
            name = os.environ.get('HANDLER_PLUGIN', 'nonebot_plugin_mortis_analysis')
            assert nonebot.load_plugin(name)
            cls.plugin = importlib.import_module(name)
        finally:
            os.chdir(original)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.bot = Mock(self_id='10001', send_group_msg=AsyncMock(),
                        send_group_forward_msg=AsyncMock(), upload_group_file=AsyncMock())

    def event(self, url):
        return GroupMessageEvent.model_validate(dict(time=1, self_id=10001, post_type='message',
            message_type='group', sub_type='normal', message_id=1, user_id=10002, group_id=10003,
            message=Message(url), original_message=Message(url), raw_message=url, font=0,
            sender={'user_id':10002,'nickname':'test','role':'member'}))

    async def test_configurable_notice_and_disable(self):
        @self.plugin.resolve_controller
        async def handler(bot, event):
            pass
        with patch.object(self.plugin.global_config, 'mortis_analysis_parse_notice', '正在读取～'):
            await handler(bot=self.bot, event=self.event('test'))
        message = self.bot.send_group_msg.await_args.kwargs['message']
        self.assertEqual([s.type for s in message], ['reply','text'])
        self.assertEqual(message.extract_plain_text(), '正在读取～')
        self.bot.send_group_msg.reset_mock()
        with patch.object(self.plugin.global_config, 'mortis_analysis_parse_notice', ''):
            await handler(bot=self.bot, event=self.event('test'))
        self.bot.send_group_msg.assert_not_awaited()

    async def test_live_query_and_video_query_routing(self):
        room = Mock(get_room_info=AsyncMock(return_value={'room_info':{
            'title':'直播','cover':'https://example.com/cover','keyframe':'https://example.com/frame'}}))
        with patch.object(self.plugin.live,'LiveRoom',return_value=room) as constructor:
            await self.plugin.bilibili(bot=self.bot,event=self.event('https://live.bilibili.com/123?from=share&x=1'))
            constructor.assert_called_once_with(room_display_id=123)
        delivery = importlib.import_module(self.plugin.__name__+'.delivery')
        url = 'https://www.bilibili.com/video/BV178xW6cE6G?from=live&source=read'
        with patch.object(delivery,'handle_bilibili_video',AsyncMock()) as handler:
            await self.plugin.bilibili(bot=self.bot,event=self.event(url))
            self.assertEqual(handler.await_args.args[2],url)

    async def test_favorite_query_order_and_empty_list(self):
        with patch.object(self.plugin,'get_video_favorite_list_content',AsyncMock(return_value={'medias':[
            {'title':'作品','cover':'https://example.com/cover','bvid':'BV178xW6cE6G'}]})) as fetch:
            await self.plugin.bilibili(bot=self.bot,event=self.event('https://space.bilibili.com/1/favlist?from=share&fid=123'))
            self.assertEqual(fetch.await_args.args,(123,))
            self.assertIn('credential',fetch.await_args.kwargs)
        nodes = self.bot.send_group_forward_msg.await_args.kwargs['messages']
        self.assertIn('BV178xW6cE6G',str(nodes[0].data['content']))
        with patch.object(self.plugin,'get_video_favorite_list_content',AsyncMock(return_value={'medias':None})):
            await self.plugin.bilibili(bot=self.bot,event=self.event('https://space.bilibili.com/1/favlist?fid=123'))
        self.assertIn('暂无可读取',str(self.bot.send_group_msg.await_args))

    async def test_short_share_routes_to_video_without_fetching_html(self):
        import httpx
        from nonebot.adapters.onebot.v11 import MessageSegment
        import json

        resolver = importlib.import_module(self.plugin.__name__+'.core.bili_link')
        delivery = importlib.import_module(self.plugin.__name__+'.delivery')
        destination = 'https://www.bilibili.com/video/BV1H6xe6PEdU?p=1&share_source=QQ'
        calls = []

        def response(request):
            calls.append(str(request.url))
            if request.url.host == 'b23.tv':
                return httpx.Response(302, headers={'Location': destination})
            return httpx.Response(412)

        client = httpx.AsyncClient(transport=httpx.MockTransport(response))
        event = self.event('')
        event.message = Message(MessageSegment.json(json.dumps(
            {'meta': {'detail_1': {'qqdocurl': 'https://b23.tv/example'}}})))
        with patch.object(resolver.httpx, 'AsyncClient', return_value=client), \
                patch.object(delivery, 'handle_bilibili_video', AsyncMock()) as handler:
            await self.plugin.bilibili(bot=self.bot, event=event)
        handler.assert_awaited_once_with(self.bot, event, destination)
        self.assertEqual(calls, ['https://b23.tv/example'])

    async def test_article_await_and_file_cleanup(self):
        article = Mock(is_note=AsyncMock(return_value=False),fetch_content=AsyncMock(),markdown=Mock(return_value='# 专栏'))
        async def upload(**kwargs):
            self.assertTrue(Path(kwargs['file']).is_file())
        self.bot.upload_group_file.side_effect = upload
        with patch.object(self.plugin.article,'Article',return_value=article):
            await self.plugin.bilibili(bot=self.bot,event=self.event('https://www.bilibili.com/read/cv123?from=share'))
        article.is_note.assert_awaited_once()
        article.turn_to_note.assert_not_called()
        path = self.bot.upload_group_file.await_args.kwargs['file']
        self.assertFalse(Path(path).exists())

    async def test_errors_reported_but_matcher_finish_preserved(self):
        @self.plugin.resolve_controller
        async def handler(bot, event):
            raise RuntimeError('private diagnostic')
        await handler(bot=self.bot,event=self.event('test'))
        message = str(self.bot.send_group_msg.await_args)
        self.assertIn('暂时未能完成',message)
        self.assertNotIn('private diagnostic',message)
        @self.plugin.resolve_controller
        async def finish(bot, event):
            raise FinishedException
        with self.assertRaises(FinishedException):
            await finish(bot=self.bot,event=self.event('test'))
