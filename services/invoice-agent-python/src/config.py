from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración completa del servicio Invoice Agent."""

    # API Settings
    api_host: str = "0.0.0.0"
    api_port: int = 7003

    # Groq/LLM Settings
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_temperature: float = 0.0
    groq_max_retries: int = 2

    # MCP Settings
    mcp_endpoint: str = "http://localhost:8200"
    mcp_timeout: float = 10.0

    # Memory Settings
    max_history_turns: int = 5

    # SQL Validation Settings
    sql_max_rows: int = 200

    model_config = SettingsConfigDict(
        env_prefix="INVOICE_AGENT_",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
