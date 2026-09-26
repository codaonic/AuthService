import time
import uuid

from jose import jwt

ISSUER = "https://auth.example.com"
RESOURCE_ID = "https://api.example.com"


def make_token(keypair, *, aud=RESOURCE_ID, iss=ISSUER, scope="profile email", ttl=600, sub=None):
    now = time.time()
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "aud": aud,
        "iss": iss,
        "scope": scope,
        "iat": now,
        "exp": now + ttl,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, keypair["pem"], algorithm="RS256", headers={"kid": keypair["kid"]})
