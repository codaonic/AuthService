from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


_dummy_hash: str | None = None


def burn_password_check(password: str) -> None:
    """Spend the same time a real check would, for an account that doesn't
    exist -- otherwise a fast "no" tells anyone which emails are registered.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("no-such-account")
    verify_password(password, _dummy_hash)
