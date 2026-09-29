from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    issuer: str = "http://localhost:8000"

    @computed_field
    @property
    def issuer_url(self) -> str:
        """Canonical issuer identity string, always trailing-slash-terminated.

        OAuth/OIDC clients (e.g. the MCP SDK's AnyHttpUrl handling) normalize
        a bare-host issuer to end in "/", so every place that asserts issuer
        *identity* (discovery's "issuer", PRM's authorization_servers, the
        "iss" claim/param, and the value JWTs are verified against) must use
        this instead of the raw `issuer` setting, or a byte-for-byte metadata
        comparison on the client side will fail. `issuer` itself stays
        unnormalized since it's also used as a base for concatenating
        endpoint paths (see discovery.py), where a trailing slash would
        produce a double slash.
        """
        return self.issuer.rstrip("/") + "/"

    db_user: str = "auth"
    db_password: str = "auth"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "auth"

    # A separate, restricted role for the app to use when actually serving
    # requests, distinct from db_user (which runs migrations and needs DDL
    # rights). Unset by default, which keeps existing deployments unchanged
    # -- runtime_database_url below falls back to the same db_user/db_password
    # as everything else. Row-Level Security (see the
    # `restrict_runtime_db_role` migration) has no effect on a Postgres
    # superuser, which db_user commonly is by default in the official
    # Postgres Docker image -- set these once you've created and password'd
    # the role that migration adds, to actually enforce RLS. See README's
    # "Row-level security" section.
    db_app_user: str | None = None
    db_app_password: str | None = None

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
    def runtime_database_url(self) -> str:
        """What the running app connects as to serve requests -- everything
        else (migrations, the CLI, first-boot schema bootstrap) uses
        database_url instead, since those legitimately need DDL rights.
        """
        user = self.db_app_user or self.db_user
        password = self.db_app_password or self.db_password
        return f"postgresql+asyncpg://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

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
    # Unset (the default) means: no default admin is seeded at all -- the
    # first person to open /admin gets an interactive setup screen to choose
    # their own email/password instead. Set both for scripted/automated
    # deployments that can't drive that UI on first boot.
    default_admin_email: str | None = None
    default_admin_password: str | None = None

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

    # Shared secret only your reverse proxy knows -- proves the mTLS
    # verification headers it sets actually came from it, not from a client
    # request that reached this app directly. Empty (the default) disables
    # mTLS client auth entirely, since trusting those headers without this
    # check would let anyone self-declare a verified certificate.
    mtls_trusted_proxy_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
