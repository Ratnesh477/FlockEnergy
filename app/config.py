import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment or defaults."""
    
    # Legacy Portal settings
    portal_base_url: str = os.getenv("PORTAL_BASE_URL", "https://urja-ops.flockenergy.tech")
    portal_username: str = os.getenv("PORTAL_USERNAME", "operator@urja.local")
    portal_password: str = os.getenv("PORTAL_PASSWORD", "urja-ops-2026")
    
    # HTTP Client settings
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15.0"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    
    # Caching and Query Engine
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "900"))  # 15 minutes
    
    # Server configuration
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
