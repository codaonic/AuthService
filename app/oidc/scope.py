from fastapi import HTTPException

from app.config import get_settings


def resolve_scope(requested: str, allowed: str) -> str:
    """Return the scope to grant: `allowed` if nothing was requested, otherwise
    `requested` if it's a subset of `allowed`. Raises 400 invalid_scope otherwise.
    """
    if not requested:
        return allowed

    if not set(requested.split()).issubset(set(allowed.split())):
        raise HTTPException(400, "invalid_scope")

    return requested


def self_registration_scope(requested: str) -> str:
    """The part of a self-registered (DCR/CIMD) client's requested scope it
    may actually hold -- see `self_registration_scopes` in config.
    """
    permitted = set(get_settings().self_registration_scopes.split())
    return " ".join(s for s in requested.split() if s in permitted)
