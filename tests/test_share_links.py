import importlib.util
import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

from nonebot.adapters.onebot.v11 import Message, MessageSegment

SPEC = importlib.util.spec_from_file_location(
    'share_links', Path(__file__).resolve().parents[1] /
    'nonebot_plugin_mortis_analysis/share_links.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ShareLinkTests(unittest.TestCase):
    def test_bilibili_links_preserve_queries_and_dynamic_ids(self):
        urls = [
            'https://www.bilibili.com/opus/1266077812525105155?from_spmid=share&plat_id=186',
            'https://t.bilibili.com/1266077812525105155?from=share&plat_id=186',
            'https://www.bilibili.com/video/BV178xW6cE6G?from=share&p=2',
            'https://b23.tv/example?from=share&p=2',
            'https://bili2233.cn/example?from=share&p=2',
        ]
        for url in urls:
            messages = [Message(url), Message(MessageSegment.json(json.dumps({'url':url})))]
            for message in messages:
                with self.subTest(url=url,kind=message[0].type):
                    self.assertEqual(MODULE.extract_bilibili_link(message),url)
        self.assertEqual(MODULE.extract_bilibili_link(Message('BV178xW6cE6G')),
                         'https://www.bilibili.com/video/BV178xW6cE6G')
        self.assertIsNone(MODULE.extract_bilibili_link(Message('普通文字')))

    def test_signed_query_survives_card_and_text_messages(self):
        import re

        class Parser:
            def extract_links(self, text):
                return re.findall(r'https://[^\s"\]]+', text)

        url = ('https://www.xiaohongshu.com/discovery/item/example?type=video'
               '&xsec_token=sample%2Btoken%3D&xsec_source=app_share')
        messages = [Message(url), Message(MessageSegment.json(json.dumps(
            {'meta': {'news': {'jumpUrl': url}}}))) ]
        for message in messages:
            with self.subTest(message_type=message[0].type):
                link = MODULE.extract_message_links(Parser(), message)[0]
                self.assertEqual(link, url)
                self.assertEqual(parse_qs(urlparse(link).query)['xsec_token'],
                                 ['sample+token='])


if __name__ == '__main__':
    unittest.main()
