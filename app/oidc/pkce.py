import base64
import hashlib


def verify_pkce(code_challenge: str, code_verifier: str | None) -> bool:
    if not code_verifier:
        return False
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == code_challenge
