import logging
import mimetypes
import os
from pathlib import Path

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lexoffice.io/v1"


def create_lexoffice_tools(api_key: str) -> list:
    """Factory: creates all Lexoffice tools bound to a specific API key."""

    def _headers():
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _auth_header():
        return {"Authorization": f"Bearer {api_key}"}

    def _get(endpoint: str, params: dict = None):
        response = requests.get(f"{BASE_URL}{endpoint}", headers=_headers(), params=params)
        response.raise_for_status()
        return response

    def _post(endpoint: str, payload: dict, params: dict = None):
        response = requests.post(f"{BASE_URL}{endpoint}", headers=_headers(), json=payload, params=params)
        response.raise_for_status()
        return response

    def _put(endpoint: str, payload: dict):
        response = requests.put(f"{BASE_URL}{endpoint}", headers=_headers(), json=payload)
        response.raise_for_status()
        return response

    def _download_pdf(endpoint: str, doc_id: str) -> str:
        """Downloads a PDF from the given endpoint and saves it to uploads/."""
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=_auth_header())
            response.raise_for_status()
            out_path = Path("uploads") / f"{doc_id}.pdf"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.content)
            logger.info("PDF saved | path=%s size=%d bytes", out_path, len(response.content))
            return f"PDF_READY:{out_path}"
        except requests.HTTPError as e:
            return f"PDF-Download fehlgeschlagen (HTTP {e.response.status_code}): {e.response.text}"

    # -------------------------------------------------------------------------
    # PROFIL
    # -------------------------------------------------------------------------

    @tool
    def get_profile() -> dict:
        """Retrieve the company profile from Lexoffice (name, address, tax info, etc.)."""
        logger.info("API call | GET /profile")
        try:
            return _get("/profile").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # KONTAKTE
    # -------------------------------------------------------------------------

    @tool
    def get_contacts(name: str = "", email: str = "", customer: bool = None, vendor: bool = None) -> list:
        """Fetch contacts from Lexoffice. Optionally filter by name, email, or role.

        Args:
            name: Filter by name (min. 3 characters, supports partial match).
            email: Filter by email (min. 3 characters, supports partial match).
            customer: If True, only return customer contacts.
            vendor: If True, only return vendor/supplier contacts.
        """
        params = {}
        if name:
            params["name"] = name
        if email:
            params["email"] = email
        if customer is not None:
            params["customer"] = str(customer).lower()
        if vendor is not None:
            params["vendor"] = str(vendor).lower()
        logger.info("API call | GET /contacts params=%s", params)
        try:
            return _get("/contacts", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_contact(contact_id: str) -> dict:
        """Retrieve a single contact by ID from Lexoffice.

        Args:
            contact_id: The UUID of the contact.
        """
        logger.info("API call | GET /contacts/%s", contact_id)
        try:
            return _get(f"/contacts/{contact_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def create_contact(
        is_company: bool,
        name: str,
        is_customer: bool = True,
        is_vendor: bool = False,
        first_name: str = "",
        email: str = "",
        phone: str = "",
        street: str = "",
        zip_code: str = "",
        city: str = "",
        country_code: str = "DE",
        note: str = "",
    ) -> dict:
        """Create a new contact in Lexoffice.

        Args:
            is_company: True for a company contact, False for a person.
            name: Company name (if is_company=True) or last name (if is_company=False).
            is_customer: Mark as customer (default True).
            is_vendor: Mark as vendor/supplier (default False).
            first_name: First name (only for person contacts).
            email: Email address.
            phone: Phone number.
            street: Street and house number.
            zip_code: Postal code.
            city: City.
            country_code: ISO 3166-1 alpha-2 country code (default 'DE').
            note: Internal note.
        """
        roles = {}
        if is_customer:
            roles["customer"] = {}
        if is_vendor:
            roles["vendor"] = {}

        payload = {"version": 0, "roles": roles}

        if is_company:
            payload["company"] = {"name": name}
        else:
            payload["person"] = {"lastName": name}
            if first_name:
                payload["person"]["firstName"] = first_name

        if any([street, zip_code, city]):
            payload["addresses"] = {
                "billing": [{"street": street, "zip": zip_code, "city": city, "countryCode": country_code}]
            }

        if email:
            payload["emailAddresses"] = {"business": [email]}
        if phone:
            payload["phoneNumbers"] = {"business": [phone]}
        if note:
            payload["note"] = note

        logger.info("API call | POST /contacts name=%s", name)
        try:
            return _post("/contacts", payload).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # RECHNUNGEN (AUSGANG)
    # -------------------------------------------------------------------------

    @tool
    def get_invoices(status: str = "any") -> list:
        """Fetch outgoing invoices from Lexoffice.

        Args:
            status: 'open', 'overdue', 'paid', 'draft', 'voided', or 'any' (default).
        """
        params = {"voucherType": "invoice", "voucherStatus": status}
        logger.info("API call | GET /voucherlist params=%s", params)
        try:
            return _get("/voucherlist", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_invoice(invoice_id: str) -> dict:
        """Retrieve full details of a specific invoice by ID.

        Args:
            invoice_id: The UUID of the invoice.
        """
        logger.info("API call | GET /invoices/%s", invoice_id)
        try:
            return _get(f"/invoices/{invoice_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def get_invoice_pdf(invoice_id: str) -> str:
        """Download the PDF for a specific invoice.

        Args:
            invoice_id: The UUID of the invoice.

        Returns:
            PDF_READY:<path> on success, or an error message.
        """
        logger.info("API call | GET /invoices/%s/file", invoice_id)
        return _download_pdf(f"/invoices/{invoice_id}/file", invoice_id)

    @tool
    def create_invoice(
        contact_id: str,
        voucher_date: str,
        line_items: list,
        currency: str = "EUR",
        tax_type: str = "net",
        finalize: bool = False,
        introduction: str = "",
        remark: str = "",
    ) -> dict:
        """Create a new outgoing invoice in Lexoffice.

        Args:
            contact_id: UUID of the contact (customer).
            voucher_date: Invoice date in ISO 8601 format (e.g. '2026-03-17T00:00:00.000+01:00').
            line_items: List of line items. Each item is a dict with:
                - type: 'custom', 'material', 'service', or 'text'
                - name: Description
                - quantity: Number (e.g. 1.0)
                - unitName: Unit (e.g. 'Stunde', 'Stück', 'Pauschal')
                - unitPrice: Dict with 'currency', 'netAmount', 'taxRatePercentage'
                Example: {"type": "custom", "name": "Beratung", "quantity": 2.0,
                          "unitName": "Stunde", "unitPrice": {"currency": "EUR",
                          "netAmount": 150.0, "taxRatePercentage": 19}}
            currency: Currency code (default 'EUR').
            tax_type: 'net' (Netto), 'gross' (Brutto), or 'vatfree' (default 'net').
            finalize: If True, finalizes the invoice immediately (no longer editable).
            introduction: Optional introduction text.
            remark: Optional closing remark.
        """
        payload = {
            "voucherDate": voucher_date,
            "address": {"contactId": contact_id},
            "lineItems": line_items,
            "totalPrice": {"currency": currency},
            "taxConditions": {"taxType": tax_type},
        }
        if introduction:
            payload["introduction"] = introduction
        if remark:
            payload["remark"] = remark

        params = {"finalize": "true"} if finalize else {}
        logger.info("API call | POST /invoices contact=%s finalize=%s", contact_id, finalize)
        try:
            return _post("/invoices", payload, params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def create_simple_invoice(
        contact_id: str,
        item_name: str,
        net_amount: float,
        tax_rate: float,
        voucher_date: str,
        quantity: float = 1.0,
        unit_name: str = "Stück",
        shipping_type: str = "service",
        finalize: bool = False,
        remark: str = "",
    ) -> dict:
        """Create a single-line outgoing invoice in Lexoffice. Use this for simple invoices with one position.

        Args:
            contact_id: UUID of the contact — get it via get_contacts first.
            item_name: Name/description of the service or product.
            net_amount: Net price per unit in EUR (e.g. 150.0).
            tax_rate: VAT rate in percent (e.g. 19.0 or 0.0).
            voucher_date: Date as 'YYYY-MM-DD' (e.g. '2026-03-17'). Also used as service/delivery date.
            quantity: Quantity (default 1.0).
            unit_name: Unit label, e.g. 'Stück', 'Stunde', 'Pauschal' (default 'Stück').
            shipping_type: Leistungsart — 'service' (Leistungsdatum, default), 'delivery' (Lieferung), 'none'.
            finalize: If True, finalizes immediately — invoice can no longer be edited.
            remark: Optional closing remark (e.g. payment terms).
        """
        from datetime import datetime, timezone, timedelta
        try:
            dt = datetime.strptime(voucher_date, "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone(timedelta(hours=1)))
            iso_date = dt.strftime("%Y-%m-%dT00:00:00.000+01:00")
        except ValueError:
            iso_date = voucher_date

        line_items = [{
            "type": "custom",
            "name": item_name,
            "quantity": quantity,
            "unitName": unit_name,
            "unitPrice": {
                "currency": "EUR",
                "netAmount": net_amount,
                "taxRatePercentage": tax_rate,
            },
        }]
        payload = {
            "voucherDate": iso_date,
            "address": {"contactId": contact_id},
            "lineItems": line_items,
            "totalPrice": {"currency": "EUR"},
            "taxConditions": {"taxType": "net"},
            "shippingConditions": {
                "shippingDate": iso_date,
                "shippingType": shipping_type,
            },
        }
        if remark:
            payload["remark"] = remark

        params = {"finalize": "true"} if finalize else {}
        logger.info("API call | POST /invoices (simple) contact=%s item=%s net=%s", contact_id, item_name, net_amount)
        try:
            return _post("/invoices", payload, params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # ANGEBOTE
    # -------------------------------------------------------------------------

    @tool
    def get_quotations(status: str = "any") -> list:
        """Fetch quotations (Angebote) from Lexoffice.

        Args:
            status: 'draft', 'open', 'accepted', 'rejected', 'voided', or 'any'.
        """
        params = {"voucherType": "quotation", "voucherStatus": status}
        logger.info("API call | GET /voucherlist type=quotation")
        try:
            return _get("/voucherlist", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_quotation(quotation_id: str) -> dict:
        """Retrieve full details of a specific quotation by ID.

        Args:
            quotation_id: The UUID of the quotation.
        """
        logger.info("API call | GET /quotations/%s", quotation_id)
        try:
            return _get(f"/quotations/{quotation_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def get_quotation_pdf(quotation_id: str) -> str:
        """Download the PDF for a specific quotation.

        Args:
            quotation_id: The UUID of the quotation.

        Returns:
            PDF_READY:<path> on success, or an error message.
        """
        logger.info("API call | GET /quotations/%s/file", quotation_id)
        return _download_pdf(f"/quotations/{quotation_id}/file", quotation_id)

    @tool
    def create_quotation(
        contact_id: str,
        voucher_date: str,
        line_items: list,
        currency: str = "EUR",
        tax_type: str = "net",
        finalize: bool = False,
        title: str = "",
        introduction: str = "",
        remark: str = "",
    ) -> dict:
        """Create a new quotation (Angebot) in Lexoffice.

        Args:
            contact_id: UUID of the contact (customer).
            voucher_date: Date in ISO 8601 format (e.g. '2026-03-17T00:00:00.000+01:00').
            line_items: List of line items (same structure as create_invoice).
            currency: Currency code (default 'EUR').
            tax_type: 'net', 'gross', or 'vatfree' (default 'net').
            finalize: If True, finalizes the quotation immediately.
            title: Optional title for the quotation.
            introduction: Optional introduction text.
            remark: Optional closing remark.
        """
        payload = {
            "voucherDate": voucher_date,
            "address": {"contactId": contact_id},
            "lineItems": line_items,
            "totalPrice": {"currency": currency},
            "taxConditions": {"taxType": tax_type},
        }
        if title:
            payload["title"] = title
        if introduction:
            payload["introduction"] = introduction
        if remark:
            payload["remark"] = remark

        params = {"finalize": "true"} if finalize else {}
        logger.info("API call | POST /quotations contact=%s finalize=%s", contact_id, finalize)
        try:
            return _post("/quotations", payload, params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # GUTSCHRIFTEN
    # -------------------------------------------------------------------------

    @tool
    def get_credit_notes(status: str = "any") -> list:
        """Fetch credit notes (Gutschriften) from Lexoffice.

        Args:
            status: 'draft', 'open', 'paid', 'voided', or 'any'.
        """
        params = {"voucherType": "creditNote", "voucherStatus": status}
        logger.info("API call | GET /voucherlist type=creditNote")
        try:
            return _get("/voucherlist", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_credit_note(credit_note_id: str) -> dict:
        """Retrieve full details of a specific credit note by ID.

        Args:
            credit_note_id: The UUID of the credit note.
        """
        logger.info("API call | GET /credit-notes/%s", credit_note_id)
        try:
            return _get(f"/credit-notes/{credit_note_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def get_credit_note_pdf(credit_note_id: str) -> str:
        """Download the PDF for a specific credit note.

        Args:
            credit_note_id: The UUID of the credit note.

        Returns:
            PDF_READY:<path> on success, or an error message.
        """
        logger.info("API call | GET /credit-notes/%s/file", credit_note_id)
        return _download_pdf(f"/credit-notes/{credit_note_id}/file", credit_note_id)

    @tool
    def create_credit_note(
        contact_id: str,
        voucher_date: str,
        line_items: list,
        currency: str = "EUR",
        tax_type: str = "net",
        finalize: bool = False,
        introduction: str = "",
        remark: str = "",
    ) -> dict:
        """Create a new credit note (Gutschrift) in Lexoffice.

        Args:
            contact_id: UUID of the contact.
            voucher_date: Date in ISO 8601 format.
            line_items: List of line items (same structure as create_invoice).
            currency: Currency code (default 'EUR').
            tax_type: 'net', 'gross', or 'vatfree' (default 'net').
            finalize: If True, finalizes immediately.
            introduction: Optional introduction text.
            remark: Optional closing remark.
        """
        payload = {
            "voucherDate": voucher_date,
            "address": {"contactId": contact_id},
            "lineItems": line_items,
            "totalPrice": {"currency": currency},
            "taxConditions": {"taxType": tax_type},
        }
        if introduction:
            payload["introduction"] = introduction
        if remark:
            payload["remark"] = remark

        params = {"finalize": "true"} if finalize else {}
        logger.info("API call | POST /credit-notes contact=%s finalize=%s", contact_id, finalize)
        try:
            return _post("/credit-notes", payload, params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # EINGANGSRECHNUNGEN / BELEGE
    # -------------------------------------------------------------------------

    @tool
    def get_purchase_invoices(status: str = "any") -> list:
        """Fetch incoming invoices / purchase vouchers (Eingangsrechnungen) from Lexoffice.

        Args:
            status: 'open', 'paid', 'draft', 'voided', or 'any'.
        """
        params = {"voucherType": "purchaseinvoice", "voucherStatus": status}
        logger.info("API call | GET /voucherlist type=purchaseinvoice")
        try:
            return _get("/voucherlist", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_voucher(voucher_id: str) -> dict:
        """Retrieve full details of a specific voucher (Eingangsbeleg) by ID.

        Args:
            voucher_id: The UUID of the voucher.
        """
        logger.info("API call | GET /vouchers/%s", voucher_id)
        try:
            return _get(f"/vouchers/{voucher_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def create_voucher(
        voucher_type: str,
        voucher_date: str,
        supplier_name: str,
        line_items: list,
        currency: str = "EUR",
        contact_id: str = "",
        note: str = "",
    ) -> dict:
        """Create a new incoming voucher/receipt (Eingangsbeleg) in Lexoffice.

        Args:
            voucher_type: Type of voucher — 'purchaseinvoice' (Eingangsrechnung) or
                          'purchasecreditnote' (Eingangskorrektur).
            voucher_date: Date in ISO 8601 format (e.g. '2026-03-17T00:00:00.000+01:00').
            supplier_name: Name of the supplier (used if no contact_id).
            line_items: List of booking line items. Each item is a dict with:
                - amount: Net amount (float)
                - taxRatePercentage: Tax rate (e.g. 19.0 or 0.0)
                - categoryId: Posting category UUID (get from get_posting_categories)
                Example: {"amount": 119.0, "taxRatePercentage": 19.0,
                          "categoryId": "<uuid>"}
            currency: Currency code (default 'EUR').
            contact_id: Optional UUID of the supplier contact in Lexoffice.
            note: Optional note.
        """
        address = {"contactId": contact_id} if contact_id else {"name": supplier_name}
        payload = {
            "type": voucher_type,
            "voucherDate": voucher_date,
            "address": address,
            "lineItems": line_items,
            "totalGrossAmount": sum(item.get("amount", 0) for item in line_items),
            "taxAmount": 0,
            "voucherItems": line_items,
            "useCollectiveContact": False,
            "remark": note,
        }
        logger.info("API call | POST /vouchers type=%s supplier=%s", voucher_type, supplier_name)
        try:
            return _post("/vouchers", payload).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # WEITERE DOKUMENTE (nur lesend)
    # -------------------------------------------------------------------------

    @tool
    def get_order_confirmations(status: str = "any") -> list:
        """Fetch order confirmations (Auftragsbestätigungen) from Lexoffice.

        Args:
            status: 'draft', 'open', 'fulfilled', 'voided', or 'any'.
        """
        params = {"voucherType": "orderConfirmation", "voucherStatus": status}
        try:
            return _get("/voucherlist", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_delivery_notes(status: str = "any") -> list:
        """Fetch delivery notes (Lieferscheine) from Lexoffice.

        Args:
            status: 'draft', 'open', 'fulfilled', 'voided', or 'any'.
        """
        params = {"voucherType": "deliveryNote", "voucherStatus": status}
        try:
            return _get("/voucherlist", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_dunnings(status: str = "any") -> list:
        """Fetch dunnings (Mahnungen) from Lexoffice.

        Args:
            status: 'draft', 'open', 'paid', 'voided', or 'any'.
        """
        params = {"voucherType": "dunning", "voucherStatus": status}
        try:
            return _get("/voucherlist", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    # -------------------------------------------------------------------------
    # ARTIKEL
    # -------------------------------------------------------------------------

    @tool
    def get_articles(article_type: str = "") -> list:
        """Fetch articles/products from Lexoffice.

        Args:
            article_type: Filter by type — 'product' (Produkt) or 'service' (Dienstleistung).
                          Leave empty for all.
        """
        params = {}
        if article_type:
            params["type"] = article_type
        logger.info("API call | GET /articles type=%s", article_type)
        try:
            return _get("/articles", params=params).json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    # -------------------------------------------------------------------------
    # WIEDERKEHRENDE VORLAGEN
    # -------------------------------------------------------------------------

    @tool
    def get_recurring_templates() -> list:
        """Fetch all recurring invoice templates (Wiederkehrende Rechnungen) from Lexoffice."""
        logger.info("API call | GET /recurring-templates")
        try:
            return _get("/recurring-templates").json().get("content", [])
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    # -------------------------------------------------------------------------
    # ZAHLUNGSBEDINGUNGEN & BUCHUNGSKATEGORIEN
    # -------------------------------------------------------------------------

    @tool
    def get_payment_conditions() -> list:
        """Fetch all available payment conditions (Zahlungsbedingungen) from Lexoffice.

        Useful to get payment condition IDs for creating invoices.
        """
        logger.info("API call | GET /payment-conditions")
        try:
            return _get("/payment-conditions").json()
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_posting_categories() -> list:
        """Fetch all posting categories (Buchungskategorien) from Lexoffice.

        Use the category UUIDs when creating vouchers (Eingangsbelege).
        """
        logger.info("API call | GET /posting-categories")
        try:
            return _get("/posting-categories").json()
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    # -------------------------------------------------------------------------
    # ZAHLUNGEN
    # -------------------------------------------------------------------------

    @tool
    def get_payments(voucher_id: str = "") -> dict:
        """Retrieve payment information for a voucher from Lexoffice.

        Args:
            voucher_id: Optional UUID of the voucher to get payments for.
        """
        params = {}
        if voucher_id:
            params["openAmount"] = voucher_id
        logger.info("API call | GET /payments voucher_id=%s", voucher_id)
        try:
            return _get("/payments", params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # DATEIEN / DOKUMENTE HOCHLADEN
    # -------------------------------------------------------------------------

    @tool
    def upload_document(file_path: str) -> str:
        """Upload a document file (PDF, image) to Lexoffice as a voucher.

        Args:
            file_path: Absolute or relative path to the file to upload.

        Returns:
            The document ID on success, or an error message.
        """
        path = Path(file_path)
        if not path.exists():
            return f"Datei nicht gefunden: '{file_path}'"
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type is None:
            mime_type = "application/octet-stream"

        logger.info("API call | POST /files filename=%s mime=%s", path.name, mime_type)
        try:
            with open(path, "rb") as f:
                response = requests.post(
                    f"{BASE_URL}/files",
                    headers=_auth_header(),
                    files={"file": (path.name, f, mime_type)},
                    data={"type": "voucher"},
                )
            response.raise_for_status()
            doc_id = response.json().get("id", "unknown")
            logger.info("Upload success | filename=%s id=%s", path.name, doc_id)
            return f"Dokument hochgeladen. ID: {doc_id}"
        except requests.HTTPError as e:
            return f"Upload fehlgeschlagen (HTTP {e.response.status_code}): {e.response.text}"

    return [
        # Profil
        get_profile,
        # Kontakte
        get_contacts, get_contact, create_contact,
        # Ausgangsrechnungen
        get_invoices, get_invoice, get_invoice_pdf, create_invoice, create_simple_invoice,
        # Angebote
        get_quotations, get_quotation, get_quotation_pdf, create_quotation,
        # Gutschriften
        get_credit_notes, get_credit_note, get_credit_note_pdf, create_credit_note,
        # Eingangsrechnungen / Belege
        get_purchase_invoices, get_voucher, create_voucher,
        # Weitere Dokumente
        get_order_confirmations, get_delivery_notes, get_dunnings,
        # Artikel & Vorlagen
        get_articles, get_recurring_templates,
        # Stammdaten
        get_payment_conditions, get_posting_categories,
        # Zahlungen & Upload
        get_payments, upload_document,
    ]


class LexofficeTool:
    """Lexoffice tools using the LEXOFFICE_API_KEY environment variable."""

    @classmethod
    def get_tools(cls) -> list:
        api_key = os.getenv("LEXOFFICE_API_KEY", "")
        return create_lexoffice_tools(api_key)
