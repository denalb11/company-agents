"""
Teams Bot Backend
=================
aiohttp web server that integrates with Microsoft Bot Framework to expose
the CompanyAgents orchestrator via Microsoft Teams.

Required environment variables:
  AZURE_APP_ID           — Bot registration App ID (client ID)
  AZURE_CLIENT_SECRET    — Bot registration client secret (app password)
  AZURE_TENANT_ID        — Azure AD tenant ID; only users from this tenant are served

Endpoint:  POST /api/messages  (port 3978)
"""

import asyncio
import logging
import os
import pathlib
import re
from datetime import datetime
from typing import Optional

import aiohttp
from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment

from src.core.config import CHAT_PREFIX_MAP, get_allowed_companies, get_company_for_channel, get_company_for_prefix
from src.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)



def _user_id(activity: Activity) -> str:
    return activity.from_property.id if activity.from_property else "unknown"

UPLOADS_DIR = pathlib.Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Bot logic
# ---------------------------------------------------------------------------

class CompanyTeamsBot:
    """Handles incoming Teams activities and delegates to the Orchestrator."""

    _MAX_HISTORY = 10  # max exchanges (user+assistant pairs) to keep per user

    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self._allowed_tenant: Optional[str] = os.environ.get("AZURE_TENANT_ID", "").strip() or None
        # Pending state per user: {user_id: {"type": "query"|"upload", "text"|"file_path": ...}}
        self._pending: dict[str, dict] = {}
        # Conversation history per user: {user_id: [(user_msg, assistant_msg), ...]}
        self._history: dict[str, list[tuple[str, str]]] = {}

    # ------------------------------------------------------------------
    # Activity dispatcher
    # ------------------------------------------------------------------

    async def on_turn(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity

        logger.info(
            "Incoming activity | type=%s user=%s channel=%s",
            activity.type,
            _user_id(activity),
            activity.channel_id or "unknown",
        )

        if activity.type == ActivityTypes.message:
            logger.info(
                "Activity detail | conversation_type=%s service_url=%s channel_data=%s",
                activity.conversation.conversation_type if activity.conversation else "?",
                activity.service_url,
                activity.channel_data,
            )
            await self._on_message(turn_context)
        elif activity.type == ActivityTypes.invoke and activity.name == "fileConsent/invoke":
            await self._handle_file_consent_invoke(turn_context)
        # Ignore other activity types (conversationUpdate, typing, etc.)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _on_message(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity

        # --- Tenant check ---
        if self._allowed_tenant:
            tenant_id = self._extract_tenant_id(activity)
            if tenant_id != self._allowed_tenant:
                logger.warning(
                    "Rejected activity from tenant '%s' (user: %s).",
                    tenant_id,
                    activity.from_property.id if activity.from_property else "unknown",
                )
                await turn_context.send_activity(
                    "Zugriff verweigert: Ihr Azure-Mandant ist nicht für diesen Bot autorisiert."
                )
                return

        user_id = _user_id(activity)

        # --- Pending state: user is answering a company question ---
        if user_id in self._pending:
            text = (activity.text or "").strip()
            company_key = CHAT_PREFIX_MAP.get(text.lower())
            if company_key:
                pending = self._pending.pop(user_id)
                if not await self._check_permission(turn_context, company_key):
                    return
                if pending["type"] == "query":
                    logger.info("Pending query resolved | user=%s company=%s", user_id, company_key)
                    await turn_context.send_activity("Ihre Anfrage wird verarbeitet, bitte warten …")
                    response, pdf_paths = await self._run_agent(pending["text"], company_key, user_id=user_id)
                    await turn_context.send_activity(response)
                    for pdf_path in pdf_paths:
                        await self._send_file_consent_card(turn_context, pathlib.Path(pdf_path))
                elif pending["type"] == "upload":
                    logger.info("Pending upload resolved | user=%s company=%s", user_id, company_key)
                    await self._process_upload(turn_context, pending["file_path"], pending["filename"], company_key)
                return
            else:
                # Invalid answer — clear state and continue normally
                self._pending.pop(user_id, None)

        # --- File / attachment ---
        if activity.attachments:
            for attachment in activity.attachments:
                if attachment.content_type == "application/vnd.microsoft.teams.file.download.info":
                    channel_name = self._extract_channel_name(activity)
                    company_key = get_company_for_channel(channel_name or "")
                    if not company_key:
                        # Download first, then ask which company
                        file_path, filename = await self._download_attachment(turn_context, attachment)
                        if file_path:
                            self._pending[user_id] = {"type": "upload", "file_path": file_path, "filename": filename}
                            await turn_context.send_activity(
                                f"Datei **{filename}** empfangen. Für welches Unternehmen?\n\n"
                                "• **ms** — multiScout\n"
                                "• **dp** — Dümpelfeld Partners\n"
                                "• **nao** — Nao Intelligence"
                            )
                        return
                    if not await self._check_permission(turn_context, company_key):
                        return
                    await self._handle_file_attachment(turn_context, attachment, company_key)
                    return

        # --- Plain text ---
        text = (activity.text or "").strip()
        if not text:
            await turn_context.send_activity(
                "Bitte senden Sie eine Textnachricht oder eine Datei als Anhang."
            )
            return

        channel_name = self._extract_channel_name(activity)
        company_key = get_company_for_channel(channel_name or "")

        # Fallback: prefix-based routing (e.g. "ms: zeige Rechnungen")
        if not company_key:
            company_key, text = get_company_for_prefix(text)

        # No company detected → ask and remember the query
        if not company_key:
            self._pending[user_id] = {"type": "query", "text": text}
            await turn_context.send_activity(
                "Für welches Unternehmen?\n\n"
                "• **ms** — multiScout\n"
                "• **dp** — Dümpelfeld Partners\n"
                "• **nao** — Nao Intelligence"
            )
            return

        logger.info(
            "Text message | user=%s length=%d channel=%s company=%s",
            _user_id(activity),
            len(text),
            channel_name or "unknown",
            company_key or "default",
        )
        if not await self._check_permission(turn_context, company_key):
            return

        try:
            await turn_context.send_activity("Ihre Anfrage wird verarbeitet, bitte warten …")
            logger.info("Sent processing message to user")
        except Exception as e:
            logger.error("Failed to send processing message: %s", e)

        try:
            response, pdf_paths = await self._run_agent(text, company_key, user_id=user_id)
            logger.info("Agent response ready, length=%d pdf_count=%d", len(response), len(pdf_paths))
            await turn_context.send_activity(response)
            logger.info("Sent agent response to user")
            for pdf_path in pdf_paths:
                await self._send_file_consent_card(turn_context, pathlib.Path(pdf_path))
        except Exception as e:
            logger.error("Failed to send agent response: %s", e)

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    async def _download_attachment(self, turn_context: TurnContext, attachment) -> tuple:
        """Download attachment to uploads/ dir. Returns (file_path, filename) or (None, None)."""
        content = attachment.content or {}
        download_url: Optional[str] = (
            content.get("downloadUrl") if isinstance(content, dict) else None
        )
        if not download_url:
            await turn_context.send_activity(
                "Die Datei konnte nicht heruntergeladen werden: keine Download-URL vorhanden."
            )
            return None, None

        filename: str = attachment.name or f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        file_path = UPLOADS_DIR / filename

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as resp:
                    if resp.status != 200:
                        await turn_context.send_activity(f"Datei-Download fehlgeschlagen (HTTP {resp.status}).")
                        return None, None
                    data = await resp.read()
            with open(file_path, "wb") as f:
                f.write(data)
            logger.info("File downloaded | user=%s filename=%s size=%d bytes", _user_id(turn_context.activity), filename, len(data))
            return str(file_path), filename
        except Exception as exc:
            logger.exception("Failed to download attachment | filename=%s", filename)
            await turn_context.send_activity(f"Beim Herunterladen der Datei ist ein Fehler aufgetreten: {exc}")
            return None, None

    async def _process_upload(self, turn_context: TurnContext, file_path: str, filename: str, company_key: str) -> None:
        """Pass a downloaded file to the agent for Lexoffice upload."""
        await turn_context.send_activity(f"Datei wird bei **{company_key}** hochgeladen …")
        agent_message = (
            f"Eine Datei wurde hochgeladen und unter folgendem Pfad gespeichert: "
            f"{file_path}. Dateiname: {filename}. "
            f"Bitte verarbeite diese Datei entsprechend."
        )
        user_id = _user_id(turn_context.activity)
        response, pdf_paths = await self._run_agent(agent_message, company_key, user_id=user_id)
        if "Document ID:" in response:
            match = re.search(r"Document ID:\s*(\S+)", response)
            if match:
                logger.info("Lexoffice upload confirmed | filename=%s document_id=%s", filename, match.group(1))
        await turn_context.send_activity(response)
        for pdf_path in pdf_paths:
            await self._send_file_consent_card(turn_context, pathlib.Path(pdf_path))

    async def _send_file_consent_card(self, turn_context: TurnContext, file_path: pathlib.Path) -> None:
        """Send a Teams file consent card (personal chat only)."""
        try:
            file_size = file_path.stat().st_size
            consent_attachment = Attachment(
                content_type="application/vnd.microsoft.teams.card.file.consent",
                name=file_path.name,
                content={
                    "description": "Rechnungs-PDF von Lexoffice",
                    "sizeInBytes": file_size,
                    "acceptContext": {"filePath": str(file_path)},
                    "declineContext": {},
                },
            )
            await turn_context.send_activity(Activity(type=ActivityTypes.message, attachments=[consent_attachment]))
            logger.info("Sent file consent card | filename=%s", file_path.name)
        except Exception as e:
            logger.error("Failed to send file consent card: %s", e)

    async def _handle_file_consent_invoke(self, turn_context: TurnContext) -> None:
        """Handle Teams fileConsent/invoke: upload file bytes when user accepts."""
        value = turn_context.activity.value or {}
        action = value.get("action", "")
        logger.info("fileConsent/invoke | action=%s value=%s", action, value)

        # Always respond to the invoke first so Teams doesn't show an error
        invoke_response = Activity(type="invokeResponse", value={"status": 200})

        if action == "decline":
            await turn_context.send_activity(invoke_response)
            return

        context = value.get("context", {})
        file_path = pathlib.Path(context.get("filePath", ""))
        upload_info = value.get("uploadInfo", {})
        upload_url: str = upload_info.get("uploadUrl", "")
        content_url: str = upload_info.get("contentUrl", "")
        unique_id: str = upload_info.get("uniqueId", "")
        file_type: str = upload_info.get("fileType", "pdf")

        # Respond to invoke immediately before doing the upload
        await turn_context.send_activity(invoke_response)

        if not file_path.exists() or not upload_url:
            logger.error("File not found or no upload URL | path=%s url=%s", file_path, upload_url)
            await turn_context.send_activity("Datei nicht gefunden für Upload.")
            return

        try:
            with open(file_path, "rb") as f:
                data = f.read()
            file_size = len(data)
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    upload_url,
                    data=data,
                    headers={
                        "Content-Type": "application/pdf",
                        "Content-Length": str(file_size),
                        "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                    },
                ) as resp:
                    resp_body = await resp.text()
                    logger.info("File PUT | status=%d body=%s", resp.status, resp_body[:200])
                    if resp.status not in (200, 201):
                        await turn_context.send_activity(f"Upload fehlgeschlagen (HTTP {resp.status}).")
                        return

            logger.info("File consent upload complete | filename=%s size=%d", file_path.name, file_size)
        except Exception as e:
            logger.exception("File consent upload failed | path=%s", file_path)
            await turn_context.send_activity(f"Fehler beim Datei-Upload: {e}")


    async def _handle_file_attachment(self, turn_context: TurnContext, attachment, company_key: str | None = None) -> None:
        """Download a Teams file attachment, save to uploads/, pass path to agent."""
        file_path, filename = await self._download_attachment(turn_context, attachment)
        if not file_path:
            return

        await self._process_upload(turn_context, file_path, filename, company_key)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _run_agent(self, message: str, company_key: str | None = None, user_id: str = "") -> tuple[str, list[str]]:
        """Run the synchronous orchestrator in a thread pool. Returns (text, pdf_paths)."""
        history = self._history.get(user_id, [])
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self.orchestrator.run, message, company_key, history)
        text, pdf_paths = result
        # Store exchange in history
        if user_id:
            self._update_history(user_id, message, text)
        return text, pdf_paths

    def _update_history(self, user_id: str, user_msg: str, assistant_msg: str) -> None:
        history = self._history.setdefault(user_id, [])
        history.append((user_msg, assistant_msg))
        if len(history) > self._MAX_HISTORY:
            history.pop(0)

    async def _check_permission(self, turn_context: TurnContext, company_key: str) -> bool:
        """Returns True if the user is allowed to access the given company."""
        aad_id = getattr(turn_context.activity.from_property, "aad_object_id", None) or ""
        allowed = get_allowed_companies(aad_id)
        if allowed == []:  # not in list at all
            await turn_context.send_activity("Zugriff verweigert: Sie haben keine Berechtigung für diesen Bot.")
            return False
        if allowed is None:  # full access
            return True
        if company_key not in allowed:
            names = {"duempelfeld": "Dümpelfeld Partners", "multiscout": "multiScout", "nao": "Nao Intelligence"}
            await turn_context.send_activity(
                f"Zugriff verweigert: Sie haben keinen Zugriff auf **{names.get(company_key, company_key)}**."
            )
            return False
        return True

    @staticmethod
    def _extract_channel_name(activity: Activity) -> str | None:
        """Extract the Teams channel name from the activity's channel data."""
        try:
            channel_data = activity.channel_data
            if isinstance(channel_data, dict):
                return channel_data.get("channel", {}).get("name")
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_tenant_id(activity: Activity) -> Optional[str]:
        """Extract the Teams tenant ID from the activity's channel data."""
        channel_data = activity.channel_data
        if not isinstance(channel_data, dict):
            return None
        tenant = channel_data.get("tenant")
        if isinstance(tenant, dict):
            return tenant.get("id")
        return None


# ---------------------------------------------------------------------------
# aiohttp request handler
# ---------------------------------------------------------------------------

async def messages(request: web.Request) -> web.Response:
    """POST /api/messages — entry point for all Bot Framework activities."""
    if "application/json" not in request.content_type:
        return web.Response(status=415, text="Content-Type must be application/json.")

    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON body.")

    activity = Activity().deserialize(body)
    auth_header: str = request.headers.get("Authorization", "")

    adapter: BotFrameworkAdapter = request.app["adapter"]
    bot: CompanyTeamsBot = request.app["bot"]

    try:
        await adapter.process_activity(activity, auth_header, bot.on_turn)
    except Exception as exc:
        logger.exception("Error while processing activity.")
        return web.Response(status=500, text=str(exc))

    return web.Response(status=200)


# ---------------------------------------------------------------------------
# App factory & server entry point
# ---------------------------------------------------------------------------

def _build_adapter() -> BotFrameworkAdapter:
    app_id = os.environ.get("AZURE_APP_ID", "")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
    tenant_id = os.environ.get("AZURE_TENANT_ID", "")

    if not tenant_id:
        raise RuntimeError(
            "AZURE_TENANT_ID is not set. Single-tenant bots require an explicit "
            "tenant so the Bot Framework can validate tokens against the correct "
            "Azure AD authority (login.microsoftonline.com/<tenant_id>)."
        )

    # channel_auth_tenant overrides the default 'botframework.com' issuer and
    # points token validation at our specific AAD tenant, which is required for
    # single-tenant app registrations (fixes AADSTS700016).
    settings = BotFrameworkAdapterSettings(
        app_id=app_id,
        app_password=client_secret,
        channel_auth_tenant=tenant_id,
    )
    adapter = BotFrameworkAdapter(settings)

    async def on_error(context: TurnContext, error: Exception):
        logger.exception("Unhandled exception in bot turn.")
        await context.send_activity(
            "Es ist ein interner Fehler aufgetreten. Bitte versuchen Sie es erneut."
        )

    adapter.on_turn_error = on_error
    return adapter


async def download_file(request: web.Request) -> web.Response:
    """GET /downloads/{filename} — serve files from the uploads directory."""
    filename = request.match_info["filename"]
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return web.Response(status=400, text="Invalid filename.")
    file_path = UPLOADS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        return web.Response(status=404, text="File not found.")
    return web.FileResponse(file_path)


def create_app(orchestrator: Orchestrator) -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()
    app["adapter"] = _build_adapter()
    app["bot"] = CompanyTeamsBot(orchestrator)
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/downloads/{filename}", download_file)
    return app


def start_teams_server(orchestrator: Orchestrator, port: int = 3978) -> None:
    """Start the Teams bot HTTP server (blocking)."""
    app = create_app(orchestrator)
    print(f"Teams Bot Server gestartet auf Port {port}.")
    print(f"Messaging-Endpunkt: http://0.0.0.0:{port}/api/messages")
    web.run_app(app, host="0.0.0.0", port=port)


# ---------------------------------------------------------------------------
# Module-level app instance for gunicorn
#
# gunicorn --worker-class aiohttp.GunicornWebWorker src.interfaces.teams_bot:app
#
# load_dotenv() is called here because gunicorn imports this module directly,
# bypassing main.py which normally handles it.
# ---------------------------------------------------------------------------

def _build_module_app() -> web.Application:
    from dotenv import load_dotenv
    load_dotenv()
    from src.core.logger import setup_logging
    setup_logging()
    from src.core.orchestrator import Orchestrator as _Orchestrator
    return create_app(_Orchestrator())


app = _build_module_app()
