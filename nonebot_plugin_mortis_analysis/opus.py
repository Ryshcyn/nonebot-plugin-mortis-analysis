"""提取 B站动态的文字与图片，兼容空模块和混排段落。"""
from urllib.parse import urlsplit


def parse_opus_content(info):
    item = info.get('item') if isinstance(info, dict) else None
    if not isinstance(item, dict):
        raise ValueError('动态内容格式无效')
    basic = item.get('basic') or {}
    title = str(basic.get('title') or '哔哩哔哩动态')
    paragraphs, images, seen = [], [], set()
    for module in item.get('modules') or []:
        if not isinstance(module, dict):
            continue
        content = module.get('module_content')
        if not isinstance(content, dict):
            continue
        for paragraph in content.get('paragraphs') or []:
            if not isinstance(paragraph, dict):
                continue
            text = paragraph.get('text') or {}
            words = []
            for node in text.get('nodes') or []:
                if not isinstance(node, dict):
                    continue
                word = node.get('word') or {}
                rich = node.get('rich') or {}
                value = word.get('words') or rich.get('text') or node.get('text') or ''
                if isinstance(value, str):
                    words.append(value)
            if words:
                paragraphs.append(''.join(words))
            picture = paragraph.get('pic') or {}
            for image in picture.get('pics') or []:
                url = image.get('url') if isinstance(image, dict) else image
                if not isinstance(url, str):
                    continue
                url = url.strip()
                if url.startswith('//'):
                    url = 'https:'+url
                parsed = urlsplit(url)
                if parsed.scheme in {'http', 'https'} and parsed.hostname and url not in seen:
                    seen.add(url)
                    images.append(url)
    return title, '\n'.join(paragraphs), images
