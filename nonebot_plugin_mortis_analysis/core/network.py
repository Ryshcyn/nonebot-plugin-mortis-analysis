"""Asynchronous HTTP entry point for platform metadata requests."""
import httpx


async def request(method, url, *, proxy=None, **kwargs):
    kwargs.setdefault('timeout', 20)
    async with httpx.AsyncClient(proxy=proxy) as client:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response
