import logging
import os
import mimetypes
from pathlib import Path
import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lexoffice.io/v1"


def _get_headers() -> dict:
    api_key = os.getenv("LEXOFFICE_API_KEY")
    if not api_key:
        raise ValueError("LEXOFFICE_API_KEY is not set.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _get_auth_header() -> dict:
    api_key = os.getenv("LEXOFFICE_API_KEY")
    if not api_key:
        raise ValueError("LEXOFFICE_API_KEY is not set.")
    return {"Authorization": f"Bearer {api_key}"}


@tool
def get_contacts() -> list:
    """Fetch all contacts from Lexoffice."""
    logger.info("API call | GET /contacts")
    response = requests.get(f"{BASE_URL}/contacts", headers=_get_headers())
    response.raise_for_status()
    result = response.json().get("content", [])
    logger.info("API response | GET /contacts status=%d count=%d", response.status_code, len(result))
    return result


@tool
def get_invoices() -> list:
    """Fetch all invoices from Lexoffice."""
    endpoint = "/voucherlist"
    params = {"voucherType": "invoice", "voucherStatus": "any"}
    logger.info("API call | GET %s params=%s", endpoint, params)
    response = requests.get(f"{BASE_URL}{endpoint}", headers=_get_headers(), params=params)
    response.raise_for_status()
    result = response.json().get("content", [])
    logger.info("API response | GET %s status=%d count=%d", endpoint, response.status_code, len(result))
    return result


@tool
def upload_document(file_path: str) -> str:
    """Upload a document file to Lexoffice for review.

    Args:
        file_path: Absolute or relative path to the file to upload.

    Returns:
        A success message containing the document ID, or an error message.
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found at '{file_path}'."
    if not path.is_file():
        return f"Error: '{file_path}' is not a file."

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type is None:
        mime_type = "application/octet-stream"

    logger.info("API call | POST /files filename=%s mime_type=%s", path.name, mime_type)
    try:
        with open(path, "rb") as f:
            response = requests.post(
                f"{BASE_URL}/files",
                headers=_get_auth_header(),
                files={"file": (path.name, f, mime_type)},
                data={"type": "voucher"},
            )
        response.raise_for_status()
        document_id = response.json().get("id", "unknown")
        logger.info("Upload success | filename=%s document_id=%s", path.name, document_id)
        return f"Document uploaded successfully. Document ID: {document_id}"
    except requests.HTTPError as e:
        logger.error(
            "Upload failed | filename=%s status=%d response=%s",
            path.name,
            e.response.status_code,
            e.response.text,
        )
        return f"Upload failed (HTTP {e.response.status_code}): {e.response.text}"
    except Exception as e:
        logger.exception("Upload failed | filename=%s", path.name)
        return f"Upload failed: {e}"


class LexofficeTool:
    """Collection of Lexoffice API tools for use with LangGraph agents."""

    tools = [get_contacts, get_invoices, upload_document]
