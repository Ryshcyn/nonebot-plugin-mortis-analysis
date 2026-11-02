"""Read local media duration without transcoding."""
import asyncio
import json
import math

class VideoProcessingError(RuntimeError):
    pass


async def run_process(*args, timeout):
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        # Do not log command arguments or stderr: other callers may probe signed media URLs.
        raise VideoProcessingError('Media process failed')
    return stdout


async def probe(path):
    raw = await run_process('ffprobe', '-v', 'error', '-show_format', '-show_streams',
                            '-of', 'json', str(path), timeout=30)
    info = json.loads(raw)
    videos = [s for s in info.get('streams', []) if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise VideoProcessingError('Video stream missing')
    duration = float(info.get('format', {}).get('duration') or videos[0].get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise VideoProcessingError('Video duration unavailable')
    return duration, info
