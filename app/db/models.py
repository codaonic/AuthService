import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
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
    # Off (default): every user in this client's login group can log into
    # it -- today's behavior, unchanged. On: only users with a matching
    # ClientAccessGrant row may, even though they're still in the same
    # group (same shared identity/password) as everyone else. This is the
    # identity-vs-authorization split real IdPs call "app assignment"
    # (Okta's per-app user assignment, Entra ID's "assignment required").
    restrict_access: Mapped[bool] = mapped_column(Boolean, default=False)
    # Off (default) everywhere, set per application: this service only
    # defines roles and reports them (see ClientRole / UserRoleAssignment,
    # and the "roles" claim added to /userinfo) -- it never enforces what a
    # role can do. That's deliberately left to the application itself.
    roles_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Off (default): new self-signups get no role, an admin assigns one
    # later. On: the signup page itself offers a role picker from this
    # client's defined roles. Meaningless unless roles_enabled and
    # allow_signup are both also on.
    allow_signup_role_selection: Mapped[bool] = mapped_column(Boolean, default=False)
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
    # Off (disabled): /token refuses to mint any access token audience-bound
    # to this resource, for every client -- see app/oidc/token.py. Clients
    # requesting a `resource` that was never registered here at all are
    # unaffected either way; this only gates resources an admin explicitly
    # catalogued and then explicitly turned off.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[str] = mapped_column(String, ForeignKey("clients.client_id"))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientAccessGrant(Base):
    """Who may log into a `restrict_access` client -- the per-app allow-list
    layered on top of a shared login group, same idea as Okta/Entra ID "app
    assignment". Irrelevant for a client with restrict_access=False, where
    anyone in the group can log in without needing a row here.
    """

    __tablename__ = "client_access_grants"
    __table_args__ = (UniqueConstraint("client_id", "user_id", name="uq_client_access_grants_client_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String, ForeignKey("clients.client_id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientRole(Base):
    """A role name an admin defines for one application -- just the string
    itself, no separate id; (client_id, name) together are the identity.
    This service only stores and reports these (see UserRoleAssignment and
    /userinfo's "roles" claim) -- what each role is allowed to do is
    entirely up to that application, not something enforced here.
    """

    __tablename__ = "client_roles"

    client_id: Mapped[str] = mapped_column(String, ForeignKey("clients.client_id"), primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRoleAssignment(Base):
    """One user holding one role (by name) on one client -- a user can hold
    several roles on the same client at once. (client_id, role) must be a
    role that client has defined (see ClientRole).
    """

    __tablename__ = "user_role_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "client_id", "role", name="uq_user_role_assignments"),
        ForeignKeyConstraint(["client_id", "role"], ["client_roles.client_id", "client_roles.name"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
