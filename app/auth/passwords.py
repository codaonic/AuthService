import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from starlette.concurrency import run_in_threadpool

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# Argon2 is deliberately slow CPU work. Called directly from a request handler
# it would stall every other request on the event loop while it runs, so
# request handlers use these instead, which run it on a worker thread.


async def hash_password_async(password: str) -> str:
    return await run_in_threadpool(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await run_in_threadpool(verify_password, password, password_hash)


_matched_secrets: set[tuple[str, str]] = set()
_MAX_MATCHED_SECRETS = 1024


async def verify_client_secret(client_secret: str, secret_hash: str) -> bool:
    """`verify_password_async` for client secrets, remembering a match.

    A service calls /token with the same secret over and over, and a client
    secret is a long random string, not a guessable password -- so after one
    full Argon2 check, a match is remembered (in memory, keyed by the stored
    hash, so a rotated secret starts over). Mismatches are never cached.
    """
    digest = hashlib.sha256(client_secret.encode()).hexdigest()
    if (digest, secret_hash) in _matched_secrets:
        return True
    if not await verify_password_async(client_secret, secret_hash):
        return False
    if len(_matched_secrets) >= _MAX_MATCHED_SECRETS:
        _matched_secrets.pop()
    _matched_secrets.add((digest, secret_hash))
    return True


_dummy_hash: str | None = None


async def burn_password_check(password: str) -> None:
    """Spend the same time a real check would, for an account that doesn't
    exist -- otherwise a fast "no" tells anyone which emails are registered.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password_async("no-such-account")
    await verify_password_async(password, _dummy_hash)
