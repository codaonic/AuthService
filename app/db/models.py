import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserPool(Base):
    """A group of clients that share one set of users.

    Clients in the same pool give their users a single shared identity
    (sign up once, log into any of them). Clients in different pools are
    fully isolated from each other's users, even on this same deployment.
    """

    __tablename__ = "user_pools"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("user_pool_id", "email", name="uq_users_pool_email"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_pools.id"), index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    mfa_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Soft delete -- see Client.deleted_at for why this isn't a hard DELETE.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_pools.id"), index=True)
    client_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    # Human-readable display name -- shown on login/consent screens instead of
    # client_id, which for dcr/cimd clients is an opaque token or a bare URL.
    # Optional: falls back to client_id wherever it's rendered.
    client_name: Mapped[str | None] = mapped_column(String, nullable=True)
    client_secret_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    client_type: Mapped[str] = mapped_column(String)  # public | confidential
    redirect_uris: Mapped[list[str]] = mapped_column(JSON, default=list)
    grant_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_scope: Mapped[str] = mapped_column(String, default="")
    registration_method: Mapped[str] = mapped_column(String, default="static")  # static | dcr | cimd
    application_type: Mapped[str] = mapped_column(String, default="web")  # web | native | service
    allow_signup: Mapped[bool] = mapped_column(Boolean, default=True)
    mtls_cert_thumbprint: Mapped[str | None] = mapped_column(String, nullable=True)
    cimd_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optional branding applied to this client's login/signup/consent pages --
    # lets a site's popup/embedded sign-in feel like their own even though
    # the actual form is still served (and the password still only ever
    # touched) by this service. Neither is validated beyond basic shape;
    # logo_url is rendered as an <img src>, brand_color as a CSS color value.
    logo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    brand_color: Mapped[str | None] = mapped_column(String, nullable=True)
    # Soft delete: set instead of removing the row, since refresh tokens,
    # consents, and audit history reference this client_id. Deleted clients
    # are also force-disabled (see api_delete_client) and filtered out of
    # every admin listing -- this column only matters for data retention.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminUser(Base):
    """An operator of this deployment, managed separately from end users --
    logs into /admin to configure pools, clients, resources, and users.
    """

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    metadata_url: Mapped[str | None] = mapped_column(String, nullable=True)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[str] = mapped_column(String, ForeignKey("clients.client_id"))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String)
    client_id: Mapped[str] = mapped_column(String, ForeignKey("clients.client_id"))
    resource_id: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String, default="")
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    rotated_from: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebAuthnCredential(Base):
    """A passkey registered by a user -- an additional login method alongside
    password + TOTP, not a replacement for either.
    """

    __tablename__ = "webauthn_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True, index=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[list[str]] = mapped_column(JSON, default=list)
    nickname: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
