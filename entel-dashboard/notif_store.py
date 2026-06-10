import base64
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from cryptography.fernet import Fernet

_DATA_DIR   = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
_NOTIF_FILE = _DATA_DIR / "notificacoes.enc"


def _make_key(secret: str) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"entel_salt_v1", 200_000)
    return base64.urlsafe_b64encode(raw)


_FERNET = Fernet(_make_key("entel_notif_2026"))


def _defaults() -> dict:
    return {"notificacoes": [], "max_count": 1000}


def load() -> dict:
    if not _NOTIF_FILE.exists():
        return _defaults()
    try:
        return json.loads(_FERNET.decrypt(_NOTIF_FILE.read_bytes()))
    except Exception:
        return _defaults()


def save(data: dict) -> None:
    _NOTIF_FILE.write_bytes(_FERNET.encrypt(json.dumps(data).encode()))


def add(ts_full: str, texto: str) -> None:
    data = load()
    data["notificacoes"].insert(0, {"ts_full": ts_full, "texto": texto})
    max_count = data.get("max_count", 1000)
    data["notificacoes"] = data["notificacoes"][:max_count]
    save(data)


def clear_all() -> None:
    data = load()
    data["notificacoes"] = []
    save(data)


def clear_old(days: int = 10) -> None:
    data = load()
    cutoff = datetime.now() - timedelta(days=days)
    data["notificacoes"] = [
        n for n in data["notificacoes"]
        if datetime.strptime(n["ts_full"], "%Y-%m-%d %H:%M:%S") >= cutoff
    ]
    save(data)


def set_max_count(n: int) -> None:
    data = load()
    data["max_count"] = n
    data["notificacoes"] = data["notificacoes"][:n]
    save(data)
