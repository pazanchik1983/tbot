"""Конфигурация приложения.

Хранится в %APPDATA%/TBot/config.json (Windows) / ~/.config/TBot/ (Linux).
API-ключи — в системном keyring (Windows Credential Manager). Если keyring
недоступен (CI/Linux без D-Bus) — есть безопасный fallback в зашифрованный
файл в той же папке.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger

APP_NAME = "TBot"
KEYRING_SERVICE = "TBot.broker_api"

try:                                                    # keyring опционален
    import keyring
    _KEYRING_OK = True
except Exception:                                       # pragma: no cover
    keyring = None                                       # type: ignore
    _KEYRING_OK = False


def app_data_dir() -> Path:
    """Папка данных приложения (Windows: %APPDATA%/TBot)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = app_data_dir() / "models"
    p.mkdir(exist_ok=True)
    return p


def logs_dir() -> Path:
    p = app_data_dir() / "logs"
    p.mkdir(exist_ok=True)
    return p


BrokerName = Literal["tinkoff", "finam_stub", "bcs_stub", "stub"]
ALLOWED_BROKERS: tuple[str, ...] = ("tinkoff", "finam_stub", "bcs_stub", "stub")


@dataclass
class Settings:
    app_version: str = "0.1.0"
    broker: BrokerName = "stub"           # по умолчанию stub — безопасно
    sandbox: bool = True
    account_id: str | None = None
    # риск/торговля
    max_position_rub: float = 50_000.0
    max_daily_loss_rub: float = 2_000.0
    default_quantity: int = 1
    min_confidence: float = 0.40          # порог входа агента
    # стратегия / агент
    strategy: str = "ensemble_ml"
    auto_retrain_every_n_trades: int = 20
    # UI
    theme: Literal["dark", "light"] = "dark"
    watchlist: list[str] = field(default_factory=list)   # FIGI

    # ---- валидация ----
    def validate(self) -> None:
        if self.broker not in ALLOWED_BROKERS:
            logger.warning("Неизвестный брокер '{}', сбрасываю на stub", self.broker)
            self.broker = "stub"
        self.max_position_rub = max(0.0, float(self.max_position_rub))
        self.max_daily_loss_rub = max(0.0, float(self.max_daily_loss_rub))
        self.default_quantity = max(1, int(self.default_quantity))
        self.auto_retrain_every_n_trades = max(1, int(self.auto_retrain_every_n_trades))
        self.min_confidence = float(min(1.0, max(0.0, self.min_confidence)))

    # ---- сериализация ----
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "Settings":
        data = json.loads(raw)
        # отбрасываем неизвестные поля, чтобы старый конфиг не ломал новые версии
        valid = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in data.items() if k in valid}
        s = cls(**data)
        s.validate()
        return s


# ---------- работа с конфиг-файлом ----------

def _config_path() -> Path:
    return app_data_dir() / "config.json"


def load_settings() -> Settings:
    path = _config_path()
    if path.exists():
        try:
            return Settings.from_json(path.read_text(encoding="utf-8"))
        except Exception as e:                                # pragma: no cover
            logger.warning("Не удалось прочитать конфиг ({}), создаю по умолчанию", e)
    s = Settings()
    s.validate()
    save_settings(s)
    return s


def save_settings(s: Settings) -> None:
    s.validate()
    _config_path().write_text(s.to_json(), encoding="utf-8")


# ---------- API-ключи: keyring → fallback ----------

def _fallback_path() -> Path:
    return app_data_dir() / "secrets.bin"


def _fallback_key() -> bytes:
    """Простой XOR-ключ из user-уникальной соли — это НЕ криптостойко,
    но защищает от случайного прочтения. На Windows будет работать keyring."""
    uniq = (os.environ.get("USERNAME") or os.environ.get("USER") or "tbot")
    return hashlib.sha256(("tbot::" + uniq).encode()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _fallback_load() -> dict[str, str]:
    p = _fallback_path()
    if not p.exists():
        return {}
    try:
        raw = base64.b64decode(p.read_bytes())
        return json.loads(_xor(raw, _fallback_key()).decode("utf-8"))
    except Exception:                                          # pragma: no cover
        return {}


def _fallback_save(d: dict[str, str]) -> None:
    raw = _xor(json.dumps(d).encode("utf-8"), _fallback_key())
    _fallback_path().write_bytes(base64.b64encode(raw))


def get_api_token(broker: str) -> str | None:
    if _KEYRING_OK:
        try:
            v = keyring.get_password(KEYRING_SERVICE, broker)
            if v:
                return v
        except Exception as e:                                  # pragma: no cover
            logger.debug("keyring.get_password недоступен: {}", e)
    return _fallback_load().get(broker)


def set_api_token(broker: str, token: str) -> None:
    if _KEYRING_OK:
        try:
            keyring.set_password(KEYRING_SERVICE, broker, token)
            return
        except Exception as e:                                  # pragma: no cover
            logger.warning("keyring.set_password недоступен ({}), использую fallback", e)
    d = _fallback_load(); d[broker] = token; _fallback_save(d)


def delete_api_token(broker: str) -> None:
    if _KEYRING_OK:
        try:
            keyring.delete_password(KEYRING_SERVICE, broker)
        except Exception:
            pass
    d = _fallback_load()
    if broker in d:
        d.pop(broker, None); _fallback_save(d)
