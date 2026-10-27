from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infrastruktura (te same zmienne co reszta Company AI OS)
    database_url: str = "postgresql://agentos:agentos@postgres:5432/agentos"
    redis_url:    str = "redis://redis:6379/0"

    # Bezpieczeństwo
    gateway_jwt_secret:      str = "change-me"
    gateway_jwt_ttl_hours:   int = 24
    gateway_encryption_key:  str = ""           # Fernet key (base64, 32B)
    gateway_allow_signup:    bool = True        # pierwszy użytkownik zawsze może się zarejestrować (zostaje adminem)
    gateway_cookie_secure:   bool = True

    # Upstreamy
    openai_base_url:     str = "https://api.openai.com/v1"
    anthropic_base_url:  str = "https://api.anthropic.com/v1"
    anthropic_version:   str = "2023-06-01"
    litellm_url:         str = "http://litellm:4000"
    litellm_master_key:  str = ""
    upstream_timeout_s:  float = 300.0

    # Klucze z env jako zapas, gdy użytkownik nie wgrał własnych
    gateway_allow_env_credentials: bool = False
    openai_api_key:    str = ""
    anthropic_api_key: str = ""

    # Raportowanie
    usd_pln_rate: float = 4.00

    # Pliki
    gateway_routing_path: Path = _ROOT / "routing.yml"
    gateway_schema_path:  Path = _ROOT.parent / "database" / "gateway.sql"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Zaślepki z .env.example — publicznie znane, więc nie mogą trafić na produkcję
_PLACEHOLDER_MARKERS = ("ZMIEN", "CHANGE-ME", "CHANGE_ME", "TWOJ_")


def validate_settings(s: Settings) -> list[str]:
    """Lista problemów z konfiguracją; pusta = można startować."""
    from cryptography.fernet import Fernet

    problems: list[str] = []
    secret = s.gateway_jwt_secret
    if len(secret) < 32 or any(m in secret.upper() for m in _PLACEHOLDER_MARKERS):
        problems.append("GATEWAY_JWT_SECRET must be a random string of at least 32 characters (not the .env.example placeholder)")
    try:
        Fernet(s.gateway_encryption_key.encode())
    except (ValueError, TypeError):
        problems.append("GATEWAY_ENCRYPTION_KEY must be a valid Fernet key (urlsafe base64 of 32 random bytes)")
    return problems
