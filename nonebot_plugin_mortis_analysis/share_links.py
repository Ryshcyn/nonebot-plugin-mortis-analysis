"""还原 OneBot 消息转义后提取分享链接。"""
from nonebot.adapters.onebot.v11.utils import unescape
import re


def message_text(message):
    return unescape(str(message))


def extract_message_links(parser, message):
    # 文本与分享卡片序列化时都会转义链接中的 &。
    return parser.extract_links(message_text(message))


def extract_bilibili_link(message):
    """提取 B站完整链接、短链或 BV 号，保留查询参数。"""
    text = message_text(message).strip().replace('\\/', '/')
    if re.fullmatch(r'BV[0-9A-Za-z]{10}', text):
        return 'https://www.bilibili.com/video/'+text
    match = re.search(r'https?://(?:(?:www|space|live|t)\.bilibili\.com|b23\.tv|bili2233\.cn)/[^\s<>"\'\\\[\]()]+', text, re.I)
    return match.group().rstrip('，。！？,.;!') if match else None
