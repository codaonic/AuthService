from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    issuer: str = "http://localhost:8000"

    db_user: str = "auth"
    db_password: str = "auth"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "auth"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @computed_field
    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    access_token_ttl_seconds: int = 600
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30
    authorization_code_ttl_seconds: int = 60

    signing_key_dir: str = "./keys"
    signing_key_algorithm: str = "RS256"

    session_cookie_name: str = "auth_session"
    session_ttl_seconds: int = 60 * 60 * 24 * 7

    admin_session_cookie_name: str = "admin_session"
    admin_session_ttl_seconds: int = 60 * 60 * 12
    default_admin_email: str = "admin@localhost"
    default_admin_password: str = "admin123!"

    rate_limit_token: str = "20/minute"
    rate_limit_authorize: str = "30/minute"
    rate_limit_admin_login: str = "10/minute"
    rate_limit_forgot_password: str = "5/hour"

    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from_address: str = "no-reply@localhost"
    email_from_name: str = "Auth Service"

    password_reset_ttl_seconds: int = 30 * 60
    email_verification_ttl_seconds: int = 60 * 60 * 24

    webauthn_rp_name: str = "Auth Service"
    webauthn_challenge_ttl_seconds: int = 5 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
