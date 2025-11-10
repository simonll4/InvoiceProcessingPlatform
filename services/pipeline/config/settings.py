import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
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


UPLOAD_DIR = _resolve_path(os.getenv("UPLOAD_DIR", DATA_ROOT / "uploads"))
PROCESSED_DIR = _resolve_path(os.getenv("PROCESSED_DIR", DATA_ROOT / "processed"))
DB_STORAGE_DIR = _resolve_path(os.getenv("DB_DIR", DATA_ROOT))

CACHE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

db_path_env = os.getenv("DB_PATH")
DEFAULT_DB_PATH = _resolve_path(db_path_env) if db_path_env else DB_STORAGE_DIR / "app.db"
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Groq API settings (OpenAI-compatible)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_BASE = os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_ALLOW_STUB = os.getenv("GROQ_ALLOW_STUB", "true").lower() in {"1", "true", "yes", "on"}

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
