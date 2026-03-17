import logging
import mimetypes
import os
from pathlib import Path

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lexoffice.io/v1"


def create_lexoffice_tools(api_key: str, sender_upn: str = "", sender_from: str = "") -> list:
    """Factory: creates all Lexoffice tools bound to a specific API key."""

    _company_sender_upn = sender_upn
    _company_sender_from = sender_from

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

    def _is_uuid(value: str) -> bool:
        import re
        return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", value.lower()))

    def _find_invoice_uuid_by_number(voucher_number: str) -> str | None:
        """Search all invoice pages for the given voucher number, return UUID or None."""
        page = 0
        while True:
            resp = requests.get(
                f"{BASE_URL}/voucherlist",
                headers=_headers(),
                params={"voucherType": "invoice", "voucherStatus": "any", "page": page, "size": 100},
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("content", []):
                if item.get("voucherNumber") == voucher_number:
                    return item["id"]
            if data.get("last", True):
                break
            page += 1
        return None

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
    # KONTAKT AKTUALISIEREN
    # -------------------------------------------------------------------------

    @tool
    def update_contact(contact_id: str, updates: dict) -> dict:
        """Update an existing contact in Lexoffice.

        Args:
            contact_id: UUID of the contact to update.
            updates: Dict of fields to update. Must include 'version' (get via get_contact first).
                     Example: {"version": 1, "note": "Neuer Hinweis"}
        """
        logger.info("API call | PUT /contacts/%s", contact_id)
        try:
            return _put(f"/contacts/{contact_id}", updates).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # ARTIKEL
    # -------------------------------------------------------------------------

    @tool
    def get_article(article_id: str) -> dict:
        """Retrieve a specific article/product by ID.

        Args:
            article_id: UUID of the article.
        """
        try:
            return _get(f"/articles/{article_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def create_article(
        name: str,
        article_type: str,
        unit_name: str,
        price: float,
        tax_rate: float,
        article_number: str = "",
        description: str = "",
    ) -> dict:
        """Create a new article/product in Lexoffice.

        Args:
            name: Article name.
            article_type: 'PRODUCT' or 'SERVICE'.
            unit_name: Unit (e.g. 'Stück', 'Stunde', 'Pauschal').
            price: Net price.
            tax_rate: VAT rate in percent (e.g. 19.0).
            article_number: Optional article number.
            description: Optional description.
        """
        payload: dict = {
            "title": name,
            "type": article_type,
            "unitName": unit_name,
            "price": {"netAmount": price, "taxRatePercentage": tax_rate, "currency": "EUR"},
        }
        if article_number:
            payload["articleNumber"] = article_number
        if description:
            payload["description"] = description
        logger.info("API call | POST /articles name=%s", name)
        try:
            return _post("/articles", payload).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def update_article(article_id: str, updates: dict) -> dict:
        """Update an existing article in Lexoffice.

        Args:
            article_id: UUID of the article.
            updates: Full article payload with updated fields (must include 'version').
        """
        logger.info("API call | PUT /articles/%s", article_id)
        try:
            return _put(f"/articles/{article_id}", updates).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def delete_article(article_id: str) -> str:
        """Delete an article from Lexoffice.

        Args:
            article_id: UUID of the article to delete.
        """
        logger.info("API call | DELETE /articles/%s", article_id)
        try:
            response = requests.delete(f"{BASE_URL}/articles/{article_id}", headers=_headers())
            response.raise_for_status()
            return f"Artikel {article_id} erfolgreich gelöscht."
        except requests.HTTPError as e:
            return f"Fehler (HTTP {e.response.status_code}): {e.response.text}"

    # -------------------------------------------------------------------------
    # BELEG AKTUALISIEREN
    # -------------------------------------------------------------------------

    @tool
    def update_voucher(voucher_id: str, updates: dict) -> dict:
        """Update an existing voucher (Eingangsbeleg) in Lexoffice.

        Args:
            voucher_id: UUID of the voucher.
            updates: Full voucher payload with updated fields (must include 'version').
        """
        logger.info("API call | PUT /vouchers/%s", voucher_id)
        try:
            return _put(f"/vouchers/{voucher_id}", updates).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # MAHNUNGEN
    # -------------------------------------------------------------------------

    @tool
    def get_dunning(dunning_id: str) -> dict:
        """Retrieve a specific dunning notice (Mahnung) by ID.

        Args:
            dunning_id: UUID of the dunning notice.
        """
        try:
            return _get(f"/dunnings/{dunning_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def get_dunning_pdf(dunning_id: str) -> str:
        """Download the PDF for a specific dunning notice.

        Args:
            dunning_id: UUID of the dunning notice.
        """
        return _download_pdf(f"/dunnings/{dunning_id}/file", dunning_id)

    @tool
    def create_dunning(
        contact_id: str,
        voucher_date: str,
        preceding_invoice_id: str,
        line_items: list,
        currency: str = "EUR",
        finalize: bool = False,
        remark: str = "",
    ) -> dict:
        """Create a dunning notice (Mahnung) in Lexoffice.

        Args:
            contact_id: UUID of the contact (debtor).
            voucher_date: Date as 'YYYY-MM-DD'.
            preceding_invoice_id: UUID of the original invoice this dunning refers to.
            line_items: Line items (same structure as create_simple_invoice).
            currency: Currency code (default 'EUR').
            finalize: If True, finalizes immediately.
            remark: Optional remark.
        """
        from datetime import datetime, timezone, timedelta
        try:
            dt = datetime.strptime(voucher_date, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=1)))
            iso_date = dt.strftime("%Y-%m-%dT00:00:00.000+01:00")
        except ValueError:
            iso_date = voucher_date

        payload = {
            "voucherDate": iso_date,
            "address": {"contactId": contact_id},
            "lineItems": line_items,
            "totalPrice": {"currency": currency},
            "taxConditions": {"taxType": "net"},
        }
        if remark:
            payload["remark"] = remark
        params = {"finalize": "true"} if finalize else {}
        if preceding_invoice_id:
            params["precedingSalesVoucherId"] = preceding_invoice_id
        logger.info("API call | POST /dunnings contact=%s", contact_id)
        try:
            return _post("/dunnings", payload, params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # LIEFERSCHEINE
    # -------------------------------------------------------------------------

    @tool
    def get_delivery_note(delivery_note_id: str) -> dict:
        """Retrieve a specific delivery note (Lieferschein) by ID.

        Args:
            delivery_note_id: UUID of the delivery note.
        """
        try:
            return _get(f"/delivery-notes/{delivery_note_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def get_delivery_note_pdf(delivery_note_id: str) -> str:
        """Download the PDF for a specific delivery note.

        Args:
            delivery_note_id: UUID of the delivery note.
        """
        return _download_pdf(f"/delivery-notes/{delivery_note_id}/file", delivery_note_id)

    @tool
    def create_delivery_note(
        contact_id: str,
        voucher_date: str,
        line_items: list,
        finalize: bool = False,
        remark: str = "",
    ) -> dict:
        """Create a delivery note (Lieferschein) in Lexoffice.

        Args:
            contact_id: UUID of the contact.
            voucher_date: Date as 'YYYY-MM-DD'.
            line_items: Line items (same structure as create_simple_invoice).
            finalize: If True, finalizes immediately.
            remark: Optional remark.
        """
        from datetime import datetime, timezone, timedelta
        try:
            dt = datetime.strptime(voucher_date, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=1)))
            iso_date = dt.strftime("%Y-%m-%dT00:00:00.000+01:00")
        except ValueError:
            iso_date = voucher_date

        payload = {
            "voucherDate": iso_date,
            "address": {"contactId": contact_id},
            "lineItems": line_items,
            "totalPrice": {"currency": "EUR"},
            "taxConditions": {"taxType": "net"},
        }
        if remark:
            payload["remark"] = remark
        params = {"finalize": "true"} if finalize else {}
        logger.info("API call | POST /delivery-notes contact=%s", contact_id)
        try:
            return _post("/delivery-notes", payload, params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # AUFTRAGSBESTÄTIGUNGEN
    # -------------------------------------------------------------------------

    @tool
    def get_order_confirmation(order_confirmation_id: str) -> dict:
        """Retrieve a specific order confirmation (Auftragsbestätigung) by ID.

        Args:
            order_confirmation_id: UUID of the order confirmation.
        """
        try:
            return _get(f"/order-confirmations/{order_confirmation_id}").json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    @tool
    def get_order_confirmation_pdf(order_confirmation_id: str) -> str:
        """Download the PDF for a specific order confirmation.

        Args:
            order_confirmation_id: UUID of the order confirmation.
        """
        return _download_pdf(f"/order-confirmations/{order_confirmation_id}/file", order_confirmation_id)

    @tool
    def create_order_confirmation(
        contact_id: str,
        voucher_date: str,
        line_items: list,
        currency: str = "EUR",
        tax_type: str = "net",
        finalize: bool = False,
        introduction: str = "",
        remark: str = "",
    ) -> dict:
        """Create an order confirmation (Auftragsbestätigung) in Lexoffice.

        Args:
            contact_id: UUID of the contact.
            voucher_date: Date as 'YYYY-MM-DD'.
            line_items: Line items (same structure as create_simple_invoice).
            currency: Currency code (default 'EUR').
            tax_type: 'net', 'gross', or 'vatfree'.
            finalize: If True, finalizes immediately.
            introduction: Optional introduction text.
            remark: Optional remark.
        """
        from datetime import datetime, timezone, timedelta
        try:
            dt = datetime.strptime(voucher_date, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=1)))
            iso_date = dt.strftime("%Y-%m-%dT00:00:00.000+01:00")
        except ValueError:
            iso_date = voucher_date

        payload = {
            "voucherDate": iso_date,
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
        logger.info("API call | POST /order-confirmations contact=%s", contact_id)
        try:
            return _post("/order-confirmations", payload, params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # STAMMDATEN (ERGÄNZT)
    # -------------------------------------------------------------------------

    @tool
    def get_print_layouts() -> list:
        """Fetch all available print layouts (Drucklayouts) from Lexoffice."""
        logger.info("API call | GET /print-layouts")
        try:
            return _get("/print-layouts").json()
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    @tool
    def get_countries() -> list:
        """Fetch all available countries with tax classifications from Lexoffice."""
        logger.info("API call | GET /countries")
        try:
            return _get("/countries").json()
        except requests.HTTPError as e:
            return [f"Fehler (HTTP {e.response.status_code}): {e.response.text}"]

    # -------------------------------------------------------------------------
    # ZAHLUNGEN (nur lesend)
    # -------------------------------------------------------------------------

    @tool
    def get_payments(voucher_id: str = "") -> dict:
        """Retrieve payment information from Lexoffice. READ-ONLY — payments cannot be created via API.

        Args:
            voucher_id: Optional UUID of a specific voucher to get payment info for.
        """
        params = {"voucherId": voucher_id} if voucher_id else {}
        logger.info("API call | GET /payments voucher_id=%s", voucher_id)
        try:
            return _get("/payments", params=params).json()
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

    # -------------------------------------------------------------------------
    # EMAIL VERSAND
    # -------------------------------------------------------------------------

    @tool
    def send_invoice_by_email(
        invoice_id: str,
        to_email: str = "",
        cc_emails: str = "",
        sender_upn: str = "",
        subject: str = "",
        body: str = "",
    ) -> str:
        """Download a Lexoffice invoice as PDF and send it by email via Microsoft 365.

        Steps performed automatically:
        1. Downloads the invoice PDF from Lexoffice.
        2. If to_email is empty, looks up the contact's email from the invoice.
        3. Sends the PDF as email attachment via Microsoft Graph API.

        Args:
            invoice_id: The UUID of the invoice in Lexoffice.
            to_email: Recipient email address. If empty, uses the contact's billing email from Lexoffice.
            cc_emails: Comma-separated CC email addresses (e.g. 'a@b.com,c@d.com'). Empty = no CC.
            sender_upn: Sender mailbox. Defaults to company config or GRAPH_SENDER_UPN env var.
            subject: Email subject. If empty, uses 'Ihre Rechnung'.
            body: HTML email body. If empty, a default German message is used.

        Returns:
            Success message or error.
        """
        from src.core.graph_api import GraphApiClient

        sender = sender_upn or _company_sender_upn or os.getenv("GRAPH_SENDER_UPN", "")
        if not sender:
            return "Fehler: Kein Absender konfiguriert. Bitte sender_upn angeben oder GRAPH_SENDER_UPN in .env setzen."

        # 1. Resolve voucher number (e.g. "RE317721") to UUID if needed
        resolved_id = invoice_id
        if not _is_uuid(invoice_id):
            try:
                found = _find_invoice_uuid_by_number(invoice_id)
                if not found:
                    return f"Rechnung '{invoice_id}' nicht gefunden. Bitte UUID oder genaue Rechnungsnummer angeben."
                resolved_id = found
            except Exception as e:
                return f"Suche nach Rechnung fehlgeschlagen: {e}"

        # 2. Get invoice details to find contact + voucher number
        try:
            invoice = _get(f"/invoices/{resolved_id}").json()
        except requests.HTTPError as e:
            return f"Rechnung nicht gefunden (HTTP {e.response.status_code}): {e.response.text}"

        voucher_number = invoice.get("voucherNumber", resolved_id)

        # 2. Auto-lookup recipient email if not provided
        recipient = to_email
        if not recipient:
            contact_id = invoice.get("address", {}).get("contactId")
            if contact_id:
                try:
                    contact = _get(f"/contacts/{contact_id}").json()
                    emails = contact.get("emailAddresses", {})
                    recipient = (
                        emails.get("business", [None])[0]
                        or emails.get("office", [None])[0]
                        or emails.get("private", [None])[0]
                    )
                except Exception:
                    pass
            if not recipient:
                return "Kein Empfänger gefunden. Bitte to_email angeben."

        # 3. Download PDF
        logger.info("send_invoice_by_email | downloading PDF for invoice %s", resolved_id)
        try:
            response = requests.get(f"{BASE_URL}/invoices/{resolved_id}/file", headers=_auth_header())
            response.raise_for_status()
            pdf_bytes = response.content
        except requests.HTTPError as e:
            return f"PDF-Download fehlgeschlagen (HTTP {e.response.status_code}): {e.response.text}"

        # 4. Send email
        email_subject = subject or f"Ihre Rechnung {voucher_number}"
        email_body = body or (
            f"<p>Sehr geehrte Damen und Herren,</p>"
            f"<p>anbei erhalten Sie Rechnung <strong>{voucher_number}</strong> als PDF-Anhang.</p>"
            f"<p>Bei Fragen stehen wir Ihnen gerne zur Verfügung.</p>"
            f"<p>Mit freundlichen Grüßen</p>"
        )
        filename = f"{voucher_number}.pdf"

        try:
            graph = GraphApiClient()
            cc_list = [a.strip() for a in cc_emails.split(",") if a.strip()] if cc_emails else []
            graph.send_email(
                sender_upn=sender,
                to_addresses=[recipient],
                cc_addresses=cc_list or None,
                subject=email_subject,
                body_html=email_body,
                attachments=[{"name": filename, "content": pdf_bytes}],
                from_address=_company_sender_from,
            )
            logger.info("Invoice emailed | invoice=%s to=%s", resolved_id, recipient)
            return f"Rechnung {voucher_number} erfolgreich an {recipient} gesendet."
        except requests.HTTPError as e:
            return f"E-Mail-Versand fehlgeschlagen (HTTP {e.response.status_code}): {e.response.text}"
        except Exception as e:
            return f"E-Mail-Versand fehlgeschlagen: {e}"

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
        get_contacts, get_contact, create_contact, update_contact,
        # Ausgangsrechnungen
        get_invoices, get_invoice, get_invoice_pdf, create_invoice, create_simple_invoice,
        # Angebote
        get_quotations, get_quotation, get_quotation_pdf, create_quotation,
        # Gutschriften
        get_credit_notes, get_credit_note, get_credit_note_pdf, create_credit_note,
        # Eingangsrechnungen / Belege
        get_purchase_invoices, get_voucher, create_voucher, update_voucher,
        # Mahnungen
        get_dunnings, get_dunning, get_dunning_pdf, create_dunning,
        # Lieferscheine
        get_delivery_notes, get_delivery_note, get_delivery_note_pdf, create_delivery_note,
        # Auftragsbestätigungen
        get_order_confirmations, get_order_confirmation, get_order_confirmation_pdf, create_order_confirmation,
        # Artikel
        get_articles, get_article, create_article, update_article, delete_article,
        # Vorlagen & Stammdaten
        get_recurring_templates, get_payment_conditions, get_posting_categories,
        get_print_layouts, get_countries,
        # Zahlungen & Upload
        get_payments, upload_document,
        # Email
        send_invoice_by_email,
    ]


class LexofficeTool:
    """Lexoffice tools using the LEXOFFICE_API_KEY environment variable."""

    @classmethod
    def get_tools(cls) -> list:
        api_key = os.getenv("LEXOFFICE_API_KEY", "")
        return create_lexoffice_tools(api_key)
