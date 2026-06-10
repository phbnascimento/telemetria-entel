import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet

_DATA_DIR    = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
_CONFIG_FILE = _DATA_DIR / "config.enc"
_DEFAULTS    = {"v_min": 210.0, "v_max": 230.0, "histerese": 2.0, "poll_interval_ms": 1000}


def _make_key(secret: str) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"entel_salt_v1", 200_000)
    return base64.urlsafe_b64encode(raw)


_FERNET = Fernet(_make_key("entel_config_2026"))


def load() -> dict:
    if not _CONFIG_FILE.exists():
        save(_DEFAULTS.copy())
        return _DEFAULTS.copy()
    try:
        cfg     = json.loads(_FERNET.decrypt(_CONFIG_FILE.read_bytes()))
        updated = False
        for key, val in _DEFAULTS.items():
            if key not in cfg:
                cfg[key] = val
                updated  = True
        if updated:
            save(cfg)
        return cfg
    except Exception:
        return _DEFAULTS.copy()


def save(cfg: dict) -> None:
    _CONFIG_FILE.write_bytes(_FERNET.encrypt(json.dumps(cfg).encode()))
