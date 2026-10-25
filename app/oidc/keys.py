import json
import os
import uuid
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from joserfc.jwk import KeySet, RSAKey

from app.config import get_settings

CURRENT_FILE = "current.json"


class KeyManager:
    def __init__(self, key_dir: str):
        self.key_dir = Path(key_dir)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        # A key file never changes once written, so each is read and parsed
        # once. The directory listing and current.json are still checked per
        # call, so a rotation (e.g. from the CLI, another process) is picked
        # up right away.
        self._keys: dict[str, RSAKey] = {}
        self._jwks: tuple[frozenset[str], dict, KeySet] | None = None

    def _current_path(self) -> Path:
        return self.key_dir / CURRENT_FILE

    def _key_path(self, kid: str) -> Path:
        return self.key_dir / f"{kid}.pem"

    def _list_kids(self) -> list[str]:
        return [p.stem for p in self.key_dir.glob("*.pem")]

    def generate_key(self, make_current: bool = True) -> str:
        kid = uuid.uuid4().hex
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # Owner-only: anyone who can read this file can sign valid tokens.
        fd = os.open(self._key_path(kid), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        if make_current:
            self._current_path().write_text(json.dumps({"kid": kid}))
        return kid

    def current_kid(self) -> str:
        if not self._current_path().exists():
            return self.generate_key(make_current=True)
        return json.loads(self._current_path().read_text())["kid"]

    def _load_private_pem(self, kid: str) -> bytes:
        return self._key_path(kid).read_bytes()

    def _key(self, kid: str) -> RSAKey:
        key = self._keys.get(kid)
        if key is None:
            key = self._keys[kid] = RSAKey.import_key(self._load_private_pem(kid))
        return key

    def signing_key(self) -> tuple[str, RSAKey]:
        kid = self.current_kid()
        return kid, self._key(kid)

    def _public(self) -> tuple[dict, KeySet]:
        self.current_kid()  # ensure at least one key exists
        kids = frozenset(self._list_kids())
        if self._jwks is None or self._jwks[0] != kids:
            keys = []
            for kid in sorted(kids):
                public_jwk = self._key(kid).as_dict(private=False)
                public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
                keys.append(public_jwk)
            jwks = {"keys": keys}
            self._jwks = (kids, jwks, KeySet.import_key_set(jwks))
        return self._jwks[1], self._jwks[2]

    def jwks(self) -> dict:
        return self._public()[0]

    def public_key_set(self) -> KeySet:
        """The public keys, ready to verify a token with."""
        return self._public()[1]

    def rotate(self) -> str:
        return self.generate_key(make_current=True)


@lru_cache
def get_key_manager() -> KeyManager:
    settings = get_settings()
    return KeyManager(settings.signing_key_dir)
