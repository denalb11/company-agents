import os

# User permissions: Azure AD Object ID → list of allowed company keys, or None = all companies
# None means full access to all companies
USER_PERMISSIONS: dict[str, list[str] | None] = {
    # --- Deniz Albayrak (alle albayrak@ Accounts) → Vollzugriff ---
    "0223b1ef-cc81-4eaa-8484-6189f6b40f1b": None,  # albayrak@duempelfeldpartners.com
    "2fef1e21-2acd-4b6c-b285-310b0449bd6e": None,  # albayrak@multiscout.com
    "45fe9502-6ed2-44b9-b4fc-49725f1e77e4": None,  # albayrak@apparelscout.com
    "02c38fd5-c388-47d8-bee7-7e882595bf77": None,  # albayrak@procurement-interim.de
    "005e5e05-ef66-457f-bbb4-685e03dad68b": None,  # albayrak@savify.ch
    "c75e1806-e0e2-4440-9867-15a1ea475efd": None,  # albayrak2@multiscout.de
    "a0a490ec-e90f-42ef-a707-5d3cf7023b06": None,  # scoutgroup albayrak
    "1629e701-1988-4971-9d0e-02e1590a8f50": None,  # s.albayrak@multiscout.de
    # --- Julia Wegen (alle wegen@ Accounts) → Vollzugriff ---
    "9e017de4-4bc2-41fb-9ce3-fbfb8cb7e553": None,  # wegen@duempelfeldpartners.com
    "e7eba269-e9ab-4cf1-8fc3-3a4c21a9d154": None,  # wegen@multiscout.de
    "42de74c6-27d4-4346-bd9e-2db35cf406a3": None,  # juliawegen@apparelscout.com
    # --- Dr. Patrick Dümpelfeld → Dümpelfeld + Nao ---
    "ed3657be-768d-483e-9585-1f14c00decf6": ["duempelfeld", "nao"],  # duempelfeld@duempelfeldpartners.com
    "6ed66c0e-2056-4ef5-8a11-b62a8dbc461f": ["duempelfeld", "nao"],  # duempelfeld@procurement-interim.de
    "081e9a62-a2ab-4263-a2bf-4a11f02877d7": ["duempelfeld", "nao"],  # duempelfeld@savify.ch
    "5b7de7b7-5fd6-4fee-89e3-435726a21980": ["duempelfeld", "nao"],  # duempelfeld@scoutgroup
    # --- Ramón Romero → nur Dümpelfeld ---
    "4f0adf15-67a0-45d2-96f5-4d539ca1a868": ["duempelfeld"],  # romero@duempelfeldpartners.com
    "b44d5ab9-9ef8-48f0-940d-9d6863aab77d": ["duempelfeld"],  # romero@procurement-interim.de
}


def get_allowed_companies(aad_object_id: str) -> list[str] | None:
    """Returns allowed company keys for a user, None = all, [] = no access."""
    if aad_object_id not in USER_PERMISSIONS:
        return []  # Not in list → no access
    return USER_PERMISSIONS[aad_object_id]  # None = all, list = specific

COMPANY_CONFIG = {
    "duempelfeld": {
        "name": "Dümpelfeld Partners",
        "system": "lexoffice",
        "api_key_env": "LEXOFFICE_API_KEY_DUEMPELFELD",
    },
    "multiscout": {
        "name": "multiScout",
        "system": "lexoffice",
        "api_key_env": "LEXOFFICE_API_KEY_MULTISCOUT",
    },
    "nao": {
        "name": "Nao Intelligence",
        "system": "lexoffice",
        "api_key_env": "LEXOFFICE_API_KEY_NAO",
    },
    "savify": {
        "name": "Savify",
        "system": "abaninja",
        "api_key_env": "ABANINJA_API_KEY_SAVIFY",
        "account_uuid_env": "ABANINJA_ACCOUNT_UUID_SAVIFY",
    },
}

# Mapping: Teams-Kanal-Name (Substring, lowercase) → company key
CHANNEL_MAP = {
    "duempelfeld": "duempelfeld",
    "dümpelfeld": "duempelfeld",
    "multiscout": "multiscout",
    "nao": "nao",
    "savify": "savify",
}

# Mapping: Chat-Prefix (lowercase, ohne Doppelpunkt) → company key
CHAT_PREFIX_MAP = {
    "ms": "multiscout",
    "multiscout": "multiscout",
    "nao": "nao",
    "dp": "duempelfeld",
    "dümpelfeld": "duempelfeld",
    "duempelfeld": "duempelfeld",
    "dümpel": "duempelfeld",
    "sv": "savify",
    "savify": "savify",
}


def get_company_for_prefix(text: str) -> tuple[str | None, str]:
    """Extracts company key and cleaned message from a prefixed text.

    Returns (company_key, cleaned_text).
    E.g. "ms: zeige Rechnungen" → ("multiscout", "zeige Rechnungen")
    """
    if ":" in text:
        prefix, _, rest = text.partition(":")
        prefix_lower = prefix.strip().lower()
        company_key = CHAT_PREFIX_MAP.get(prefix_lower)
        if company_key:
            return company_key, rest.strip()
    return None, text


def get_company_for_channel(channel_name: str) -> str | None:
    """Returns company key for a Teams channel name (substring match), or None."""
    lower = channel_name.lower()
    for substring, company_key in CHANNEL_MAP.items():
        if substring in lower:
            return company_key
    return None


def get_api_key_for_company(company_key: str) -> str:
    """Returns API key for a company. Raises if not configured."""
    config = COMPANY_CONFIG.get(company_key)
    if not config:
        raise ValueError(f"Unknown company key: '{company_key}'")
    env_var = config["api_key_env"]
    api_key = os.getenv(env_var)
    if not api_key:
        raise ValueError(f"Environment variable '{env_var}' is not set for company '{company_key}'.")
    return api_key


def get_abaninja_credentials(company_key: str) -> tuple[str, str]:
    """Returns (api_key, account_uuid) for an AbaNinja company. Raises if not configured."""
    config = COMPANY_CONFIG.get(company_key)
    if not config or config.get("system") != "abaninja":
        raise ValueError(f"'{company_key}' is not an AbaNinja company.")
    api_key = os.getenv(config["api_key_env"])
    account_uuid = os.getenv(config["account_uuid_env"])
    if not api_key:
        raise ValueError(f"Environment variable '{config['api_key_env']}' is not set.")
    if not account_uuid:
        raise ValueError(f"Environment variable '{config['account_uuid_env']}' is not set.")
    return api_key, account_uuid
