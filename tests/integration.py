"""Isolated validation: fake OneBot sends, real Chromium, optional public video download."""
import asyncio
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.chdir(tempfile.mkdtemp(prefix='mortis-resolver-'))

import nonebot
nonebot.init(driver='~fastapi',localstore_use_cwd=True,htmlrender_browser_executable_path='/usr/bin/chromium',
             htmlrender_browser_args='--no-sandbox --disable-dev-shm-usage',log_level='WARNING')
from nonebot.adapters.onebot.v11 import Adapter, GroupMessageEvent, PrivateMessageEvent
nonebot.get_driver().register_adapter(Adapter)
assert nonebot.load_plugin('nonebot_plugin_mortis_analysis') is not None
plugin = importlib.import_module('nonebot_plugin_mortis_analysis')
from nonebot_plugin_mortis_analysis import card, delivery, settings
from nonebot_plugin_mortis_analysis.core import common


def event(group=True):
    raw = dict(time=1,self_id=10001,post_type='message',message_type='group' if group else 'private',
        sub_type='normal' if group else 'friend',message_id=1,user_id=10002,
        message='https://www.bilibili.com/video/BV1dRx16pE3J',original_message='test',raw_message='test',
        font=0,sender={'user_id':10002,'nickname':'offline','sex':'unknown','age':0,'role':'member'})
    if group:
        raw['group_id']=10003
    return (GroupMessageEvent if group else PrivateMessageEvent).model_validate(raw)


class FakeBot:
    self_id='10001'
    def __init__(self):
        self.calls=[]
    async def record(self,**kw):
        self.calls.append(kw)
        message=kw.get('message')
        if message:
            for segment in message:
                if segment.type=='video':
                    assert Path(segment.data['file'].removeprefix('file://')).is_file()
        for node in kw.get('messages', []):
            for segment in node.data['content']:
                if segment.type in {'image','video'}:
                    assert Path(segment.data['file'].removeprefix('file://')).is_file()
        return {'message_id':len(self.calls)}
    send_group_msg=record
    send_private_msg=record
    send_group_forward_msg=record
    send_private_forward_msg=record
    upload_group_file=record
    upload_private_file=record


async def main():
    from nonebot_plugin_htmlrender import get_browser
    fixtures = Path('/fixtures')
    data = json.loads((fixtures/'data.json').read_text())
    for key in ('cover','avatar'):
        data[key]=(fixtures/data[key]).read_bytes()
    for c in data['comments']:
        c['avatar']=(fixtures/c['avatar']).read_bytes()
        c.pop('emotes',None)
    browser = await get_browser()
    # Every allowed parsing request replies to the source before calling the parser.
    for group in (True,False):
        bot=FakeBot();ev=event(group)
        async def parse_after_notice(*args,**kwargs):
            assert len(bot.calls)==1
            message=bot.calls[0]['message']
            assert [s.type for s in message]==['reply','text']
            assert message[0].data['id']==str(ev.message_id)
            assert message.extract_plain_text()=='小睦将为你解析～'
        with patch.object(delivery,'handle_public_share',side_effect=parse_after_notice) as handler:
            await plugin.dy(bot=bot,event=ev)
            handler.assert_awaited_once()
        plugin.resolve_shutdown_list_in_memory.append(plugin.get_id_both(ev))
        try:
            bot.calls.clear()
            with patch.object(delivery,'handle_public_share',AsyncMock()) as handler:
                await plugin.dy(bot=bot,event=ev)
                assert not bot.calls
                handler.assert_not_awaited()
        finally:
            plugin.resolve_shutdown_list_in_memory.clear()
        values=settings.get_store().current()
        with patch.object(settings.get_store(),'current',return_value=dict(values,blocked_platforms=['dy'])):
            with patch.object(delivery,'handle_public_share',AsyncMock()) as handler:
                await plugin.dy(bot=bot,event=ev)
                assert not bot.calls
                handler.assert_not_awaited()
    captured=[]
    from nonebot_plugin_htmlrender import html_to_pic
    async def screenshot(**kw):
        page = await browser.new_page(viewport=kw['viewport'])
        await page.set_content(kw['html'])
        await page.evaluate('document.fonts.ready')
        await page.locator('img').evaluate_all('(imgs)=>Promise.all(imgs.map(i=>i.decode()))')
        assert await page.locator('img').evaluate_all('(imgs)=>imgs.every(i=>i.naturalWidth>0)')
        assert await page.evaluate('document.documentElement.scrollWidth===760')
        assert not await page.locator('script').count()
        captured.append(await page.content())
        result=await page.screenshot(full_page=True)
        await page.close()
        return result
    with patch.object(card,'html_to_pic',screenshot):
        image=await card.render_card(data)
        Path('/report/bilibili-online-layout.png').write_bytes(image)
        attack=dict(data,title='<script>alert(1)</script>',comments=[{'username':'<img src=x>','content':'<script>bad()</script>','like':None}])
        await card.render_card(attack)
        assert '&lt;script&gt;' in captured[-1]
        assert '—' in captured[-1]
        for platform in ('douyin','xiaohongshu'):
            await card.render_card(dict(data,platform=platform,stats={}))
        fake=FakeBot()
        for group in (True,False):
            ev=event(group)
            start=len(fake.calls)
            await delivery.send_information(fake,ev,data,data['comments'],bili=True)
            path=common.CACHE_DIR/'offline.mp4'
            path.write_bytes((fixtures/'assets/video.mp4').read_bytes())
            await delivery.send_local_video(fake,ev,str(path))
            assert [m['message'][0].type for m in fake.calls[start:]]==['image','video']
            assert ('group_id' in fake.calls[start])==group
            path.unlink()
        ev=event()
        plugin.comment_shutdown_list_in_memory.append(ev.group_id)
        await delivery.send_information(fake,ev,data,data['comments'],bili=True)
        assert '热门评论' not in captured[-1]
        plugin.comment_shutdown_list_in_memory.clear()
        # Shared public-share handler: ordered sends and delayed cleanup.
        async def download(*a,**kw):
            p=common.CACHE_DIR/'public.mp4';p.write_bytes((fixtures/'assets/video.mp4').read_bytes());return str(p)
        parser=type('Parser',(),{'name':'douyin','extract_links':lambda self,text:['https://www.douyin.com/video/1'],
            'parse':AsyncMock(return_value=dict(data,video_urls=[['https://example.invalid/video']],image_urls=[],audio_urls=[],hot_comments=[]))})()
        before=len(fake.calls)
        with patch.object(common,'download_video',download):
            await delivery.handle_public_share(fake,ev,parser)
        assert [m['message'][0].type for m in fake.calls[before:]]==['image','video']
        assert not (common.CACHE_DIR/'public.mp4').exists()
        # Oversize local files are rejected before probing or processing.
        from nonebot_plugin_mortis_analysis import video_limits, video_processing
        large=common.CACHE_DIR/'large.mp4'
        with large.open('wb') as stream:
            stream.truncate(video_limits.maximum_bytes()+1)
        rejected=FakeBot()
        with patch.object(video_processing,'run_process',AsyncMock()) as process:
            try:
                await delivery.send_local_video(rejected,ev,str(large))
                raise AssertionError('Oversize video accepted')
            except video_limits.VideoLimitExceeded as exc:
                assert exc.reason=='size'
            process.assert_not_awaited()
        assert not rejected.calls
        large.unlink()
        # Bilibili duration limits stop before requesting or downloading a stream.
        from nonebot_plugin_mortis_analysis.core import bili23 as bili_core, comment as comment_core
        raw_info=json.loads((fixtures/'video-info.json').read_text())
        raw_info['duration']=7200;raw_info['pages'][0]['duration']=7200
        fake_video=type('Video',(),{'get_info':AsyncMock(return_value=raw_info),
            'get_download_url':AsyncMock()})()
        long_bot=FakeBot()
        with patch.object(delivery.video,'Video',return_value=fake_video),patch.object(bili_core,'download_b_file',AsyncMock()) as download_b,patch.object(comment_core,'get_bilibili_comments',AsyncMock(return_value=[])),patch.object(delivery,'send_information',AsyncMock(return_value=True)):
            await delivery.handle_bilibili_video(long_bot,ev,data['url'])
        fake_video.get_download_url.assert_not_awaited()
        download_b.assert_not_awaited()
        assert len(long_bot.calls)==1
        assert '时长上限' in str(long_bot.calls[0]['message'])
        assert '原链接' in str(long_bot.calls[0]['message'])
        assert '解析失败' not in str(long_bot.calls[0]['message'])
        # Unknown sizes are bounded while streaming; known oversize stops at the header.
        from aiohttp import web
        async def known(request):
            response=web.StreamResponse(headers={'Content-Length':str(video_limits.maximum_bytes()+1)})
            await response.prepare(request)
            await response.write_eof()
            return response
        async def unknown(request):
            response=web.StreamResponse()
            await response.prepare(request)
            try:
                for i in range(8):
                    await response.write(b'x'*512)
            except ConnectionResetError:
                pass
            return response
        async def small(request):
            return web.Response(body=b'small video payload')
        app=web.Application();app.router.add_get('/known',known);app.router.add_get('/unknown',unknown);app.router.add_get('/small',small)
        runner=web.AppRunner(app);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        origin='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        try:
            for suffix,cap in [('/known',video_limits.maximum_bytes()),('/unknown',1024)]:
                before_files=set(common.CACHE_DIR.glob('*'))
                try:
                    await common.download_video(origin+suffix,max_bytes=cap)
                    raise AssertionError('Download limit not enforced')
                except video_limits.VideoLimitExceeded:
                    pass
                assert set(common.CACHE_DIR.glob('*'))==before_files
            downloaded=await common.download_video(origin+'/small',max_bytes=1024)
            assert Path(downloaded).read_bytes()==b'small video payload'
            Path(downloaded).unlink()
        finally:
            await runner.cleanup()
        # A CDN 403 must try the same image's backup, then continue the gallery.
        gallery=dict(data,video_urls=[],audio_urls=[],image_urls=[['one'],['403','backup-two'],['three'],['four']],hot_comments=[])
        parser.parse=AsyncMock(return_value=gallery)
        attempted=[]
        async def image_download(url,**kw):
            attempted.append(url)
            if url=='403':
                raise RuntimeError('403')
            path=common.CACHE_DIR/(url+'.jpg');path.write_bytes(b'image');return str(path)
        before=len(fake.calls)
        with patch.object(common,'download_img',image_download),patch.object(delivery,'send_information',AsyncMock(return_value=True)):
            await delivery.handle_public_share(fake,ev,parser)
        assert attempted==['one','403','backup-two','three','four']
        assert len(fake.calls[before:])==1
        assert len(fake.calls[-1]['messages'])==4
        assert all(n.data['content'][0].type=='image' for n in fake.calls[-1]['messages'])
        assert not list(common.CACHE_DIR.glob('*'))
        # Single images also forward; mixed galleries keep videos in standalone messages.
        for group in (True,False):
            gallery['image_urls']=[['one']]
            gallery['video_urls']=[['video']]
            parser.parse=AsyncMock(return_value=gallery)
            mixed=FakeBot()
            with patch.object(common,'download_img',image_download),patch.object(common,'download_video',download),patch.object(delivery,'send_information',AsyncMock(return_value=True)):
                await delivery.handle_public_share(mixed,event(group),parser)
            assert len(mixed.calls)==2
            assert len(mixed.calls[0]['messages'])==1
            assert mixed.calls[1]['message'][0].type=='video'
            assert ('group_id' in mixed.calls[0])==group
            assert not list(common.CACHE_DIR.glob('*'))
        # If every URL for one image fails, remaining images still send with one precise notice.
        gallery['image_urls']=[['one'],['403'],['three'],['four']]
        gallery['video_urls']=[]
        parser.parse=AsyncMock(return_value=gallery)
        before=len(fake.calls)
        with patch.object(common,'download_img',image_download),patch.object(delivery,'send_information',AsyncMock(return_value=True)):
            await delivery.handle_public_share(fake,ev,parser)
        sent=fake.calls[before:]
        assert len(sent)==2 and len(sent[0]['messages'])==3
        assert '1 张图片' in str(sent[-1]['message']) and '分享解析失败' not in str(sent[-1]['message'])
        assert not list(common.CACHE_DIR.glob('*'))
        parser.parse=AsyncMock(side_effect=RuntimeError('metadata unavailable'))
        before=len(fake.calls)
        await delivery.handle_public_share(fake,ev,parser)
        assert len(fake.calls)==before+1 and '分享解析失败' in str(fake.calls[-1]['message'])
        # Chromium failure keeps metadata and sends comments through the existing text mode.
        with patch.object(card,'html_to_pic',AsyncMock(side_effect=RuntimeError('offline browser'))):
            await delivery.send_information(fake,ev,data,[],bili=True)
        assert fake.calls[-1]['message'][0].type=='text'
    if os.environ.get('RESOLVER_LIVE_CHECK')=='1':
        # Only fake sends: downloads the user-provided public video without connecting to QQ.
        bot=FakeBot()
        await delivery.handle_bilibili_video(bot,event(),data['url'])
        assert [m['message'][0].type for m in bot.calls]==['image','video'], [str(m)[:100] for m in bot.calls]
        assert not list(common.CACHE_DIR.glob('*'))
    await browser.close()
    print('PASS: isolated package load, Chromium rendering, 3 themes, escaped external text, real image decoding, group/private order, disabled comments, public media cleanup, render fallback, optional live Bilibili download; no QQ sends')


asyncio.run(main())
