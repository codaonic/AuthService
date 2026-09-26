import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_pools.id"), index=True)
    client_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    client_secret_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    client_type: Mapped[str] = mapped_column(String)  # public | confidential
    redirect_uris: Mapped[list[str]] = mapped_column(JSON, default=list)
    grant_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_scope: Mapped[str] = mapped_column(String, default="")
    registration_method: Mapped[str] = mapped_column(String, default="static")  # static | dcr | cimd
    application_type: Mapped[str] = mapped_column(String, default="web")  # web | native | service
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
