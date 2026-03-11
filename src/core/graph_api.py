"""
Microsoft Graph API helper
==========================
Provides async helpers for uploading files to a user's OneDrive via the
Microsoft Graph API (client credentials flow).

Required Azure App Registration permissions (Application type, admin consent):
  - Files.ReadWrite.All

Required environment variables (already used by the bot):
  AZURE_APP_ID           — Bot registration App ID
  AZURE_CLIENT_SECRET    — Bot registration client secret
  AZURE_TENANT_ID        — Azure AD tenant ID
"""

import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphApiClient:
    """Async Graph API client using client credentials (app-only) flow."""

    def __init__(self):
        self._tenant_id = os.environ.get("AZURE_TENANT_ID", "")
        self._client_id = os.environ.get("AZURE_APP_ID", "")
        self._client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
        self._token: str | None = None
        self._token_expires: float = 0

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                resp.raise_for_status()
                result = await resp.json()
                self._token = result["access_token"]
                self._token_expires = time.time() + result.get("expires_in", 3600)
                logger.info("Graph API token acquired, expires in %ds", result.get("expires_in", 3600))
                return self._token

    async def upload_pdf_to_user_drive(self, user_aad_id: str, filename: str, content: bytes) -> dict:
        """Upload PDF to user's OneDrive root folder.

        Args:
            user_aad_id: The user's Azure AD Object ID.
            filename: Filename to use in OneDrive (e.g. 'invoice_12345.pdf').
            content: Raw PDF bytes.

        Returns:
            Graph API drive item dict (contains 'id', 'webUrl', '@microsoft.graph.downloadUrl').

        Raises:
            aiohttp.ClientResponseError: On HTTP errors (e.g. 403 if permission not granted).
        """
        token = await self._get_token()
        url = f"{GRAPH_BASE}/users/{user_aad_id}/drive/root:/{filename}:/content"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/pdf",
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, data=content) as resp:
                if not resp.ok:
                    body = await resp.text()
                    logger.error(
                        "Graph upload failed | user=%s file=%s status=%d body=%s",
                        user_aad_id, filename, resp.status, body[:500],
                    )
                resp.raise_for_status()
                item = await resp.json()
                logger.info(
                    "Graph upload success | user=%s file=%s item_id=%s",
                    user_aad_id, filename, item.get("id"),
                )
                return item
