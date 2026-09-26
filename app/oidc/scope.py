from fastapi import HTTPException


def resolve_scope(requested: str, allowed: str) -> str:
    """Return the scope to grant: `allowed` if nothing was requested, otherwise
    `requested` if it's a subset of `allowed`. Raises 400 invalid_scope otherwise.
    """
    if not requested:
        return allowed

    if not set(requested.split()).issubset(set(allowed.split())):
        raise HTTPException(400, "invalid_scope")

    return requested
