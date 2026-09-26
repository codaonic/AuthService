import json
import uuid
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk

from app.config import get_settings

CURRENT_FILE = "current.json"


class KeyManager:
    def __init__(self, key_dir: str):
        self.key_dir = Path(key_dir)
        self.key_dir.mkdir(parents=True, exist_ok=True)

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
        self._key_path(kid).write_bytes(pem)
        if make_current:
            self._current_path().write_text(json.dumps({"kid": kid}))
        return kid

    def current_kid(self) -> str:
        if not self._current_path().exists():
            return self.generate_key(make_current=True)
        return json.loads(self._current_path().read_text())["kid"]

    def _load_private_pem(self, kid: str) -> bytes:
        return self._key_path(kid).read_bytes()

    def signing_key(self) -> tuple[str, bytes]:
        kid = self.current_kid()
        return kid, self._load_private_pem(kid)

    def jwks(self) -> dict:
        self.current_kid()  # ensure at least one key exists
        keys = []
        for kid in self._list_kids():
            pem = self._load_private_pem(kid)
            public_jwk = jwk.construct(pem, algorithm="RS256").public_key().to_dict()
            public_jwk.pop("d", None)
            public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
            keys.append(public_jwk)
        return {"keys": keys}

    def rotate(self) -> str:
        return self.generate_key(make_current=True)


@lru_cache
def get_key_manager() -> KeyManager:
    settings = get_settings()
    return KeyManager(settings.signing_key_dir)
