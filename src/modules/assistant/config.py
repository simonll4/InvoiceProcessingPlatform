"""Configuration for the assistant service."""

import os
from pathlib import Path

# Database
DB_PATH = Path(os.getenv("DB_PATH", "/app/data/app.db"))
CACHE_DB_PATH = Path(os.getenv("CACHE_DB_PATH", "/app/data/cache/app.db"))

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


LLM_API_BASE = os.getenv("LLM_API_BASE", os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1"))
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))
LLM_MODEL_SQL = os.getenv("LLM_MODEL_SQL", os.getenv("GROQ_MODEL_SQL", LLM_MODEL))
LLM_MODEL_SUMMARY = os.getenv(
    "LLM_MODEL_SUMMARY",
    os.getenv("GROQ_MODEL_SUMMARY", LLM_MODEL),
)
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("GROQ_API_KEY", ""))

# MCP Configuration
MCP_ENABLED = _env_bool("MCP_ENABLED", True)
MCP_SQLITE_URL = os.getenv("MCP_SQLITE_URL", "http://mcp-sqlite:3000")

# Assistant behavior
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))  # Increased for context continuity
SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", "1800"))  # 30min
ENABLE_DEBUG_MODE = _env_bool("ENABLE_DEBUG_MODE", False)
DISABLE_FALLBACK = _env_bool("DISABLE_FALLBACK", False)  # Enabled for robustness

_default_llm_timeout = 45
LLM_REQUEST_TIMEOUT = int(
    os.getenv("LLM_REQUEST_TIMEOUT", str(_default_llm_timeout))
)

# Security - read-only enforcement
ALLOWED_SQL_KEYWORDS = {"SELECT", "PRAGMA", "EXPLAIN"}
FORBIDDEN_SQL_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "TRUNCATE",
    "REPLACE",
    "ATTACH",
    "DETACH",
}
