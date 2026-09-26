"""Sunucu tarafı yapılandırma (ortam değişkenleri / .env).

Sırlar (API anahtarları, bot token, SMTP parolası) yalnızca burada okunur ve
tarayıcıya hiçbir zaman gönderilmez. Kullanıcıya ait tercihler (konum, ürünler,
bülten saati ...) veri tabanındaki `settings` tablosundadır: bkz. settings_store.py.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Basit .env okuyucu: var olan ortam değişkenlerinin üzerine yazmaz."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "evet", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass
class Config:
    data_dir: Path
    database_path: Path
    app_base_url: str
    secret_key: str
    secret_key_is_ephemeral: bool
    app_password: str
    default_timezone: str

    # HTTP
    http_user_agent: str
    http_timeout: float
    http_max_bytes: int
    trusted_hosts: list[str] = field(default_factory=list)

    # Telegram
    telegram_bot_token: str = ""
    telegram_mode: str = "polling"          # polling|webhook|off
    telegram_webhook_secret: str = ""

    # E-posta
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_security: str = "starttls"         # starttls|ssl|none
    email_from: str = ""

    # LLM
    llm_provider: str = "none"              # anthropic|openai_compat|none
    llm_model: str = ""
    llm_effort: str = "medium"
    llm_fallbacks: str = "default"          # default|off (yalnızca Anthropic)
    anthropic_api_key: str = ""
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""
    llm_daily_budget_usd: float = 1.0
    llm_max_calls_per_day: int = 60
    llm_price_in_per_mtok: float = 5.0
    llm_price_out_per_mtok: float = 25.0

    # Web araması
    search_provider: str = "none"           # brave|searxng|none
    brave_api_key: str = ""
    searxng_url: str = ""
    search_daily_limit: int = 30

    # Veri sağlayıcıları
    weather_provider: str = "open_meteo"
    open_meteo_base: str = "https://api.open-meteo.com"
    open_meteo_geocoding_base: str = "https://geocoding-api.open-meteo.com"
    tcmb_url: str = "https://www.tcmb.gov.tr/kurlar/today.xml"
    truncgil_url: str = "https://finans.truncgil.com/today.json"
    market_json_url: str = ""
    market_json_mapping: str = ""
    youtube_transcripts: bool = False

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai_compat":
            return bool(self.openai_compat_base_url and self.llm_model)
        return False

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token) and self.telegram_mode != "off"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.email_from)

    @property
    def search_configured(self) -> bool:
        if self.search_provider == "brave":
            return bool(self.brave_api_key)
        if self.search_provider == "searxng":
            return bool(self.searxng_url)
        return False


_config: Config | None = None


def load_config(env_file: str | None = None, reload: bool = False) -> Config:
    global _config
    if _config is not None and not reload:
        return _config
    _load_dotenv(Path(env_file or os.environ.get("BULTEN_ENV_FILE", ".env")))

    data_dir = Path(_str("DATA_DIR", "./data")).resolve()
    db_path = Path(_str("DATABASE_PATH", str(data_dir / "bulten.db"))).resolve()

    secret = _str("APP_SECRET_KEY")
    ephemeral = False
    if not secret:
        # Kalıcı olmayan anahtar: imzalı bağlantılar yeniden başlatmada geçersizleşir.
        secret = secrets.token_urlsafe(32)
        ephemeral = True

    provider = _str("LLM_PROVIDER", "none").lower()
    default_model = {"anthropic": "claude-opus-5"}.get(provider, "")

    trusted = [h.strip().lower() for h in _str("TRUSTED_FETCH_HOSTS").split(",") if h.strip()]

    _config = Config(
        data_dir=data_dir,
        database_path=db_path,
        app_base_url=_str("APP_BASE_URL", "http://localhost:8000").rstrip("/"),
        secret_key=secret,
        secret_key_is_ephemeral=ephemeral,
        app_password=_str("APP_PASSWORD"),
        default_timezone=_str("DEFAULT_TIMEZONE", "Europe/Istanbul"),
        http_user_agent=_str(
            "HTTP_USER_AGENT",
            "KisiselSabahBulteni/0.1 (+kişisel kullanım; tek kullanıcılı bülten)",
        ),
        http_timeout=_float("HTTP_TIMEOUT", 25.0),
        http_max_bytes=_int("HTTP_MAX_BYTES", 6_000_000),
        trusted_hosts=trusted,
        telegram_bot_token=_str("TELEGRAM_BOT_TOKEN"),
        telegram_mode=_str("TELEGRAM_MODE", "polling").lower(),
        telegram_webhook_secret=_str("TELEGRAM_WEBHOOK_SECRET"),
        smtp_host=_str("SMTP_HOST"),
        smtp_port=_int("SMTP_PORT", 587),
        smtp_user=_str("SMTP_USER"),
        smtp_password=_str("SMTP_PASSWORD"),
        smtp_security=_str("SMTP_SECURITY", "starttls").lower(),
        email_from=_str("EMAIL_FROM"),
        llm_provider=provider,
        llm_model=_str("LLM_MODEL", default_model),
        llm_effort=_str("LLM_EFFORT", "medium").lower(),
        llm_fallbacks=_str("LLM_FALLBACKS", "default").lower(),
        anthropic_api_key=_str("ANTHROPIC_API_KEY"),
        openai_compat_base_url=_str("OPENAI_COMPAT_BASE_URL").rstrip("/"),
        openai_compat_api_key=_str("OPENAI_COMPAT_API_KEY"),
        llm_daily_budget_usd=_float("LLM_DAILY_BUDGET_USD", 1.0),
        llm_max_calls_per_day=_int("LLM_MAX_CALLS_PER_DAY", 60),
        llm_price_in_per_mtok=_float("LLM_PRICE_IN_PER_MTOK", 5.0),
        llm_price_out_per_mtok=_float("LLM_PRICE_OUT_PER_MTOK", 25.0),
        search_provider=_str("SEARCH_PROVIDER", "none").lower(),
        brave_api_key=_str("BRAVE_API_KEY"),
        searxng_url=_str("SEARXNG_URL").rstrip("/"),
        search_daily_limit=_int("SEARCH_DAILY_LIMIT", 30),
        weather_provider=_str("WEATHER_PROVIDER", "open_meteo"),
        open_meteo_base=_str("OPEN_METEO_BASE", "https://api.open-meteo.com").rstrip("/"),
        open_meteo_geocoding_base=_str(
            "OPEN_METEO_GEOCODING_BASE", "https://geocoding-api.open-meteo.com"
        ).rstrip("/"),
        tcmb_url=_str("TCMB_URL", "https://www.tcmb.gov.tr/kurlar/today.xml"),
        truncgil_url=_str("TRUNCGIL_URL", "https://finans.truncgil.com/today.json"),
        market_json_url=_str("MARKET_JSON_URL"),
        market_json_mapping=_str("MARKET_JSON_MAPPING"),
        youtube_transcripts=_bool("YOUTUBE_TRANSCRIPTS", False),
    )
    return _config


def set_config(cfg: Config) -> None:
    """Testler için yapılandırmayı doğrudan ayarla."""
    global _config
    _config = cfg
