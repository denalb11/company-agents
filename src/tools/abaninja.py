"""
Abaninja API tools
==================
LangGraph tools for the Swiss21 AbaNinja accounting platform.

Required environment variables (per company):
  ABANINJA_API_KEY_<COMPANY>        — Bearer token from AbaNinja Settings → API Tokens
  ABANINJA_ACCOUNT_UUID_<COMPANY>   — Account UUID from AbaNinja Settings → Company
"""

import base64
import logging
import mimetypes
import pathlib

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

BASE_URL = "https://api.abaninja.ch"

_ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/tiff"}


def create_abaninja_tools(api_key: str, account_uuid: str) -> list:
    """Factory: creates AbaNinja tools bound to a specific API key and account UUID."""

    def _headers():
        return {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    @tool
    def get_companies() -> list:
        """Fetch all company contacts from Abaninja."""
        endpoint = f"/accounts/{account_uuid}/addresses/v2/companies"
        logger.info("API call | GET %s", endpoint)
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=_headers())
            response.raise_for_status()
            result = response.json().get("data", [])
            logger.info("API response | GET %s status=%d count=%d", endpoint, response.status_code, len(result))
            return result
        except requests.HTTPError as e:
            logger.error("GET %s failed | status=%d", endpoint, e.response.status_code)
            return [f"Fehler beim Abruf (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_invoices() -> list:
        """Fetch all invoices from Abaninja."""
        endpoint = f"/accounts/{account_uuid}/documents/v2/invoices"
        logger.info("API call | GET %s", endpoint)
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=_headers())
            response.raise_for_status()
            result = response.json().get("data", [])
            logger.info("API response | GET %s status=%d count=%d", endpoint, response.status_code, len(result))
            return result
        except requests.HTTPError as e:
            logger.error("GET %s failed | status=%d", endpoint, e.response.status_code)
            return [f"Fehler beim Abruf (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_invoice_actions(invoice_uuid: str) -> list:
        """Get available actions for a specific invoice in Abaninja.

        Use this to find out what actions can be performed on an invoice,
        such as marking it as paid, sending it, or cancelling it.

        Args:
            invoice_uuid: The UUID of the invoice.

        Returns:
            List of available actions for the invoice.
        """
        endpoint = f"/accounts/{account_uuid}/documents/v2/invoices/{invoice_uuid}/actions"
        logger.info("API call | GET %s", endpoint)
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=_headers())
            response.raise_for_status()
            result = response.json().get("data", [])
            logger.info("API response | GET %s status=%d count=%d", endpoint, response.status_code, len(result))
            return result
        except requests.HTTPError as e:
            logger.error("GET %s failed | status=%d", endpoint, e.response.status_code)
            return [f"Fehler beim Abruf (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def execute_invoice_action(invoice_uuid: str, action: str) -> dict:
        """Execute an action on a specific invoice in Abaninja.

        Common actions: 'mark_as_paid', 'send', 'cancel', 'book'.
        Use get_invoice_actions first to see which actions are available.

        Args:
            invoice_uuid: The UUID of the invoice.
            action: The action to execute (e.g. 'mark_as_paid').

        Returns:
            The API response after executing the action.
        """
        endpoint = f"/accounts/{account_uuid}/documents/v2/invoices/{invoice_uuid}/actions"
        logger.info("API call | PATCH %s action=%s", endpoint, action)
        try:
            response = requests.patch(
                f"{BASE_URL}{endpoint}",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"action": action},
            )
            response.raise_for_status()
            logger.info("API response | PATCH %s status=%d", endpoint, response.status_code)
            return response.json()
        except requests.HTTPError as e:
            logger.error("PATCH %s failed | status=%d", endpoint, e.response.status_code)
            return {"error": f"Fehler (HTTP {e.response.status_code}): {e.response.text}"}

    @tool
    def upload_receipt(file_path: str) -> dict:
        """Upload a receipt or supplier invoice (PDF, JPG, PNG) to Abaninja.

        The file is submitted to Abaninja's imported-invoices endpoint where the
        built-in AI (DeepO) extracts the relevant fields automatically.

        Args:
            file_path: Absolute or relative path to the file on disk.

        Returns:
            The API response data for the created document.
        """
        path = pathlib.Path(file_path)
        if not path.exists():
            return {"error": f"Datei nicht gefunden: {file_path}"}

        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type not in _ALLOWED_MIME_TYPES:
            return {"error": f"Nicht unterstützter Dateityp '{mime_type}'. Erlaubt: PDF, JPG, PNG, TIFF"}

        endpoint = f"/accounts/{account_uuid}/documents/v2/invoices/import"
        logger.info("API call | POST %s file=%s mime=%s", endpoint, path.name, mime_type)

        file_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        try:
            response = requests.post(
                f"{BASE_URL}{endpoint}",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"documents": [{"documentUrl": f"data:{mime_type};base64,{file_b64}"}]},
            )
            logger.info("API response | POST %s status=%d", endpoint, response.status_code)
            if not response.ok:
                logger.error("Upload error | %s", response.text)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            logger.error("POST %s failed | status=%d", endpoint, e.response.status_code)
            return {"error": f"Upload fehlgeschlagen (HTTP {e.response.status_code}): {e.response.text}"}

    return [get_companies, get_invoices, get_invoice_actions, execute_invoice_action, upload_receipt]
