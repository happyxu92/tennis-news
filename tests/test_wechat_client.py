from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.publisher.wechat_client import WeChatClient


@pytest.mark.asyncio
async def test_wechat_client_reuses_access_token_for_multiple_requests(tmp_path: Path) -> None:
    requests: list[tuple[str, str]] = []
    cover_file = tmp_path / "cover.jpg"
    cover_file.write_bytes(b"image-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
        if request.url.path == "/cgi-bin/material/add_material":
            return httpx.Response(200, json={"media_id": "cover-media", "url": "https://mmbiz.test/1"})
        if request.url.path == "/cgi-bin/draft/add":
            return httpx.Response(200, json={"media_id": "draft-media"})
        if request.url.path == "/cgi-bin/freepublish/submit":
            return httpx.Response(200, json={"publish_id": "publish-1"})
        if request.url.path == "/cgi-bin/freepublish/get":
            return httpx.Response(
                200,
                json={
                    "publish_id": "publish-1",
                    "publish_status": 0,
                    "article_id": "article-1",
                    "article_detail": {
                        "count": 1,
                        "item": [{"idx": 1, "article_url": "https://mp.weixin.qq.com/s/test"}],
                    },
                    "fail_idx": [],
                },
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://api.weixin.qq.com",
    ) as http_client:
        client = WeChatClient(
            app_id="app-id",
            app_secret="app-secret",
            http_client=http_client,
        )

        cover = await client.upload_cover_image(cover_file)
        draft_media_id = await client.create_draft(
            {
                "article_type": "news",
                "title": "Title",
                "author": "Author",
                "digest": "Digest",
                "content": "<p>Hello</p>",
                "thumb_media_id": cover["media_id"],
            }
        )
        publish_id = await client.submit_publish(draft_media_id)
        publish_status = await client.get_publish_status(publish_id)

    assert cover["media_id"] == "cover-media"
    assert draft_media_id == "draft-media"
    assert publish_id == "publish-1"
    assert publish_status["publish_status"] == 0
    assert requests.count(("GET", "/cgi-bin/token")) == 1


@pytest.mark.asyncio
async def test_wechat_client_uploads_inline_images(tmp_path: Path) -> None:
    inline_file = tmp_path / "inline.png"
    inline_file.write_bytes(b"png-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
        if request.url.path == "/cgi-bin/media/uploadimg":
            return httpx.Response(200, json={"url": "https://mmbiz.test/inline.png", "errcode": 0})
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://api.weixin.qq.com",
    ) as http_client:
        client = WeChatClient(
            app_id="app-id",
            app_secret="app-secret",
            http_client=http_client,
        )
        url = await client.upload_inline_image(inline_file)

    assert url == "https://mmbiz.test/inline.png"
