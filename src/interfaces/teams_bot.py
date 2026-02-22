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
from datetime import datetime
from typing import Optional

import aiohttp
from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes

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

    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self._allowed_tenant: Optional[str] = os.environ.get("AZURE_TENANT_ID", "").strip() or None

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
            await self._on_message(turn_context)
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

        # --- File / attachment ---
        if activity.attachments:
            for attachment in activity.attachments:
                if attachment.content_type == "application/vnd.microsoft.teams.file.download.info":
                    await self._handle_file_attachment(turn_context, attachment)
                    return

        # --- Plain text ---
        text = (activity.text or "").strip()
        if not text:
            await turn_context.send_activity(
                "Bitte senden Sie eine Textnachricht oder eine Datei als Anhang."
            )
            return

        logger.info(
            "Text message | user=%s length=%d",
            _user_id(activity),
            len(text),
        )
        await turn_context.send_activity("Ihre Anfrage wird verarbeitet, bitte warten …")
        response = await self._run_agent(text)
        await turn_context.send_activity(response)

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    async def _handle_file_attachment(self, turn_context: TurnContext, attachment) -> None:
        """Download a Teams file attachment, save to uploads/, pass path to agent."""
        content = attachment.content or {}
        download_url: Optional[str] = (
            content.get("downloadUrl") if isinstance(content, dict) else None
        )

        if not download_url:
            await turn_context.send_activity(
                "Die Datei konnte nicht heruntergeladen werden: keine Download-URL vorhanden."
            )
            return

        filename: str = (
            attachment.name
            or f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        file_path = UPLOADS_DIR / filename

        # Download the file
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as resp:
                    if resp.status != 200:
                        await turn_context.send_activity(
                            f"Datei-Download fehlgeschlagen (HTTP {resp.status})."
                        )
                        return
                    data = await resp.read()

            with open(file_path, "wb") as f:
                f.write(data)

            logger.info(
                "File upload received | user=%s filename=%s size=%d bytes",
                _user_id(turn_context.activity),
                filename,
                len(data),
            )
        except Exception as exc:
            logger.exception("Failed to download attachment | filename=%s", filename)
            await turn_context.send_activity(
                f"Beim Herunterladen der Datei ist ein Fehler aufgetreten: {exc}"
            )
            return

        await turn_context.send_activity(
            f"Datei '{filename}' wurde empfangen und gespeichert. Verarbeitung läuft …"
        )

        # Pass the saved file path to the agent
        agent_message = (
            f"Eine Datei wurde hochgeladen und unter folgendem Pfad gespeichert: "
            f"{file_path.resolve()}. Dateiname: {filename}. "
            f"Bitte verarbeite diese Datei entsprechend."
        )
        response = await self._run_agent(agent_message)

        # Log the Lexoffice document ID if the agent confirms a successful upload
        if "Document ID:" in response:
            import re
            match = re.search(r"Document ID:\s*(\S+)", response)
            if match:
                logger.info(
                    "Lexoffice upload confirmed | filename=%s document_id=%s",
                    filename,
                    match.group(1),
                )

        await turn_context.send_activity(response)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _run_agent(self, message: str) -> str:
        """Run the synchronous orchestrator in a thread pool to avoid blocking."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.orchestrator.run, message)

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


def create_app(orchestrator: Orchestrator) -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()
    app["adapter"] = _build_adapter()
    app["bot"] = CompanyTeamsBot(orchestrator)
    app.router.add_post("/api/messages", messages)
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
