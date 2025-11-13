import os
from pathlib import Path

from dotenv import load_dotenv


# Locate the project root and load environment overrides for local/dev usage.
# From src/modules/pipeline/config/settings.py -> need to go up 4 levels to reach /app
PROJECT_ROOT = Path(__file__).resolve().parents[4]
ENV_PATH = PROJECT_ROOT / "configs" / "env" / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:  # pragma: no cover - fallback for tests
    load_dotenv()

DATA_ROOT = PROJECT_ROOT / "data"
CACHE_DIR = DATA_ROOT / "cache"


def _resolve_path(value: str | Path) -> Path:
    if isinstance(value, Path):
        path = value
    else:
        path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path

    # Directories used across ingestion, caching, and persistence.


UPLOAD_DIR = _resolve_path(os.getenv("UPLOAD_DIR", DATA_ROOT / "uploads"))
PROCESSED_DIR = _resolve_path(os.getenv("PROCESSED_DIR", DATA_ROOT / "processed"))
DB_STORAGE_DIR = _resolve_path(os.getenv("DB_DIR", DATA_ROOT))

CACHE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

db_path_env = os.getenv("DB_PATH")
DEFAULT_DB_PATH = (
    _resolve_path(db_path_env) if db_path_env else DB_STORAGE_DIR / "app.db"
)
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


PIPELINE_LLM_MODEL = os.getenv(
    "PIPELINE_LLM_MODEL", os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
)
PIPELINE_LLM_API_BASE = os.getenv(
    "PIPELINE_LLM_API_BASE",
    os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1"),
)
PIPELINE_LLM_API_KEY = os.getenv(
    "PIPELINE_LLM_API_KEY", os.getenv("GROQ_API_KEY", "")
)
PIPELINE_LLM_ALLOW_STUB = _get_bool_env(
    "PIPELINE_LLM_ALLOW_STUB",
    _get_bool_env("GROQ_ALLOW_STUB", True),
)

# Rate Limiter Settings (conservative defaults for free tier)
# Free tier limits: RPM=30, RPD=1000, TPM=12K, TPD=100K
# Ultra-conservative to account for tool calling (2x calls per assistant query)
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "12"))  # 12/30 (40% for safety)
RATE_LIMIT_RPD = int(os.getenv("RATE_LIMIT_RPD", "400"))  # 400/1000 (40%)
RATE_LIMIT_TPM = int(os.getenv("RATE_LIMIT_TPM", "8000"))  # 8K/12K (67%)
RATE_LIMIT_TPD = int(os.getenv("RATE_LIMIT_TPD", "70000"))  # 70K/100K (70%)

# Database
db_url_env = os.getenv("DB_URL")
if db_url_env and db_url_env.startswith("sqlite:///"):
    # Support both sqlite:///relative and sqlite:////absolute
    raw_path = db_url_env.split("sqlite:///", 1)[1]
    resolved = _resolve_path(raw_path)
    DB_URL = f"sqlite:///{resolved.as_posix()}"
elif db_url_env:
    DB_URL = db_url_env
else:
    DB_URL = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

# Defaults
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "UNK")
PDF_OCR_DPI = int(os.getenv("PDF_OCR_DPI", "300"))
PDF_OCR_MAX_PAGES = int(os.getenv("PDF_OCR_MAX_PAGES", "5"))
TEXT_MIN_LENGTH = int(os.getenv("TEXT_MIN_LENGTH", "120"))

# Samples path (optional helper for CLI/tests)
SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", DATA_ROOT / "samples"))
