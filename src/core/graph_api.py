"""
Microsoft Graph API helper
==========================
Provides async helpers for uploading files to a user's OneDrive, and
sync helpers for sending emails via the Microsoft Graph API
(client credentials flow).

Required Azure App Registration permissions (Application type, admin consent):
  - Files.ReadWrite.All
  - Mail.Send

Required environment variables (already used by the bot):
  AZURE_APP_ID           — Bot registration App ID
  AZURE_CLIENT_SECRET    — Bot registration client secret
  AZURE_TENANT_ID        — Azure AD tenant ID
"""

import base64
import logging
import os
import time

import aiohttp
import requests

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

    def send_email(
        self,
        sender_upn: str,
        to_addresses: list[str],
        subject: str,
        body_html: str,
        attachments: list[dict] | None = None,
        from_address: str = "",
        cc_addresses: list[str] | None = None,
    ) -> None:
        """Send an email via Microsoft Graph API (sync, client credentials).

        Args:
            sender_upn: UPN or email of the sender mailbox (e.g. 'albayrak@multiscout.com').
            to_addresses: List of recipient email addresses.
            subject: Email subject.
            body_html: HTML body of the email.
            attachments: Optional list of dicts with 'name' (filename) and 'content' (bytes).

        Raises:
            requests.HTTPError: On API errors.
        """
        token = self._get_token_sync()
        recipients = [{"emailAddress": {"address": addr}} for addr in to_addresses]

        message: dict = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": recipients,
        }
        if from_address:
            message["from"] = {"emailAddress": {"address": from_address}}
        if cc_addresses:
            message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_addresses]
        if attachments:
            message["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentBytes": base64.b64encode(att["content"]).decode("utf-8"),
                    "contentType": "application/pdf",
                }
                for att in attachments
            ]

        url = f"{GRAPH_BASE}/users/{sender_upn}/sendMail"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json={"message": message, "saveToSentItems": True})
        response.raise_for_status()
        logger.info("Email sent | from=%s to=%s subject=%s", sender_upn, to_addresses, subject)

    def _get_token_sync(self) -> str:
        """Synchronous token fetch using requests."""
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        response = requests.post(url, data=data)
        response.raise_for_status()
        result = response.json()
        self._token = result["access_token"]
        self._token_expires = time.time() + result.get("expires_in", 3600)
        logger.info("Graph API token acquired (sync), expires in %ds", result.get("expires_in", 3600))
        return self._token
