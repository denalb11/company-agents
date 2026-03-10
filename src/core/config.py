import os

COMPANY_CONFIG = {
    "duempelfeld": {
        "name": "Dümpelfeld Partners",
        "api_key_env": "LEXOFFICE_API_KEY_DUEMPELFELD",
    },
    "multiscout": {
        "name": "multiScout",
        "api_key_env": "LEXOFFICE_API_KEY_MULTISCOUT",
    },
    "nao": {
        "name": "Nao Intelligence",
        "api_key_env": "LEXOFFICE_API_KEY_NAO",
    },
}

# Mapping: Teams-Kanal-Name (Substring, lowercase) → company key
CHANNEL_MAP = {
    "duempelfeld": "duempelfeld",
    "dümpelfeld": "duempelfeld",
    "multiscout": "multiscout",
    "nao": "nao",
}


def get_company_for_channel(channel_name: str) -> str | None:
    """Returns company key for a Teams channel name (substring match), or None."""
    lower = channel_name.lower()
    for substring, company_key in CHANNEL_MAP.items():
        if substring in lower:
            return company_key
    return None


def get_api_key_for_company(company_key: str) -> str:
    """Returns Lexoffice API key for a company key. Raises if not configured."""
    config = COMPANY_CONFIG.get(company_key)
    if not config:
        raise ValueError(f"Unknown company key: '{company_key}'")
    env_var = config["api_key_env"]
    api_key = os.getenv(env_var)
    if not api_key:
        raise ValueError(f"Environment variable '{env_var}' is not set for company '{company_key}'.")
    return api_key
