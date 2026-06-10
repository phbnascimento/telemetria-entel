import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet

_DATA_DIR   = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
_USERS_FILE = _DATA_DIR / "users.enc"

_DEFAULT_EMAILS = {
    "admin": "pedro.brito.7677@gmail.com",
    "user":  "evertzmn48@gmail.com",
}


def _make_key(secret: str) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"entel_salt_v1", 200_000)
    return base64.urlsafe_b64encode(raw)


_FERNET = Fernet(_make_key("entel_users_2026"))


def _hash_pw(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000).hex()


def _load_users() -> dict:
    if not _USERS_FILE.exists():
        return _create_defaults()
    try:
        users = json.loads(_FERNET.decrypt(_USERS_FILE.read_bytes()))
        updated = False
        for username, user in users.items():
            if "email" not in user:
                user["email"] = _DEFAULT_EMAILS.get(username, "")
                updated = True
            if "notif_ativa" not in user:
                user["notif_ativa"] = True
                updated = True
        if updated:
            _save_users(users)
        return users
    except Exception:
        return _create_defaults()


def _save_users(users: dict) -> None:
    _USERS_FILE.write_bytes(_FERNET.encrypt(json.dumps(users).encode()))


def _create_defaults() -> dict:
    users = {}
    for username, role in [("user", "user"), ("admin", "admin")]:
        salt = os.urandom(16)
        users[username] = {
            "salt":        salt.hex(),
            "hash":        _hash_pw("entel", salt),
            "role":        role,
            "email":       _DEFAULT_EMAILS.get(username, ""),
            "notif_ativa": True,
        }
    _save_users(users)
    return users


def authenticate(username: str, password: str) -> str | None:
    """Retorna a role ('user' | 'admin') ou None se inválido."""
    users = _load_users()
    if username not in users:
        return None
    u = users[username]
    if _hash_pw(password, bytes.fromhex(u["salt"])) == u["hash"]:
        return u["role"]
    return None


def get_email(username: str) -> str:
    return _load_users().get(username, {}).get("email", "")


def update_email(username: str, email: str) -> None:
    users = _load_users()
    if username in users:
        users[username]["email"] = email
        _save_users(users)


def get_notif_ativa(username: str) -> bool:
    return _load_users().get(username, {}).get("notif_ativa", True)


def update_notif_ativa(username: str, ativa: bool) -> None:
    users = _load_users()
    if username in users:
        users[username]["notif_ativa"] = ativa
        _save_users(users)


def get_notification_emails() -> list[str]:
    """Retorna e-mails dos usuários com notificações ativas."""
    return [
        u["email"]
        for u in _load_users().values()
        if u.get("email") and u.get("notif_ativa", True)
    ]
