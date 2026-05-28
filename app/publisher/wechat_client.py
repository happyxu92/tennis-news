from __future__ import annotations

import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


class WeChatAPIError(RuntimeError):
    """Raised when a WeChat API call returns an error."""

    def __init__(
        self,
        message: str,
        *,
        errcode: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.errcode = errcode
        self.response = response or {}


class WeChatClient:
    """Minimal async WeChat Official Account publishing client."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        timeout: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.weixin.qq.com",
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self._http_client = http_client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
        )
        self._owns_http_client = http_client is None
        self._access_token: str | None = None
        self._access_token_expires_at: datetime | None = None

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def get_access_token(self) -> str:
        now = datetime.now(UTC)
        if (
            self._access_token
            and self._access_token_expires_at
            and now < self._access_token_expires_at
        ):
            return self._access_token

        if not self.app_id or not self.app_secret:
            raise ValueError("WeChat app credentials are not configured")

        response = await self._http_client.get(
            "/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": self.app_id,
                "secret": self.app_secret,
            },
        )
        data = self._decode_response(response)
        token = data.get("access_token")
        if not token:
            raise WeChatAPIError("Failed to fetch WeChat access token", response=data)

        expires_in = int(data.get("expires_in") or 7200)
        self._access_token = token
        self._access_token_expires_at = now + timedelta(seconds=max(expires_in - 300, 60))
        return token

    async def upload_cover_image(self, image_path: str | Path) -> dict[str, str | None]:
        data = await self._upload_file(
            "/cgi-bin/material/add_material",
            image_path,
            params={"type": "image"},
        )
        media_id = data.get("media_id")
        if not media_id:
            raise WeChatAPIError("WeChat cover upload did not return media_id", response=data)
        return {"media_id": media_id, "url": data.get("url")}

    async def upload_inline_image(self, image_path: str | Path) -> str:
        data = await self._upload_file("/cgi-bin/media/uploadimg", image_path)
        url = data.get("url")
        if not url:
            raise WeChatAPIError("WeChat inline image upload did not return url", response=data)
        return url

    async def create_draft(self, article: dict[str, Any]) -> str:
        data = await self._post_json("/cgi-bin/draft/add", {"articles": [article]})
        media_id = data.get("media_id")
        if not media_id:
            raise WeChatAPIError("WeChat draft creation did not return media_id", response=data)
        return media_id

    async def submit_publish(self, media_id: str) -> str:
        data = await self._post_json("/cgi-bin/freepublish/submit", {"media_id": media_id})
        publish_id = data.get("publish_id")
        if not publish_id:
            raise WeChatAPIError(
                "WeChat publish submission did not return publish_id",
                response=data,
            )
        return publish_id

    async def get_publish_status(self, publish_id: str) -> dict[str, Any]:
        data = await self._post_json("/cgi-bin/freepublish/get", {"publish_id": publish_id})
        publish_status = data.get("publish_status")
        if publish_status is None:
            raise WeChatAPIError(
                "WeChat publish status did not return publish_status",
                response=data,
            )
        return data

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = await self.get_access_token()
        response = await self._http_client.post(
            path,
            params={"access_token": access_token},
            json=payload,
        )
        return self._decode_response(response)

    async def _upload_file(
        self,
        path: str,
        image_path: str | Path,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        file_path = Path(image_path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"WeChat upload file does not exist: {file_path}")

        access_token = await self.get_access_token()
        query = {"access_token": access_token}
        if params:
            query.update(params)

        mime_type, _ = mimetypes.guess_type(file_path.name)
        with file_path.open("rb") as handle:
            response = await self._http_client.post(
                path,
                params=query,
                files={
                    "media": (
                        file_path.name,
                        handle,
                        mime_type or "application/octet-stream",
                    )
                },
            )
        return self._decode_response(response)

    def _decode_response(self, response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        data = response.json()
        errcode = data.get("errcode")
        if errcode not in (None, 0):
            errmsg = data.get("errmsg") or "unknown WeChat API error"
            raise WeChatAPIError(
                f"WeChat API error {errcode}: {errmsg}",
                errcode=errcode,
                response=data,
            )
        return data
