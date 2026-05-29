from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://vigsocial:vigsocial_dev@localhost:5432/vigsocial"
    redis_url: str = "redis://localhost:6379/0"
    # TTL da memória de conversa do VigIA no Redis (horas)
    assist_session_ttl_hours: int = 168
    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    bootstrap_superadmin_email: str | None = None
    bootstrap_superadmin_password: str | None = None
    bootstrap_superadmin_name: str = "Super Admin"
    # Se true, ao subir a API atualiza a senha do e-mail de bootstrap já existente (útil após trocar env no EasyPanel).
    bootstrap_superadmin_sync_password: bool = False

    @field_validator("bootstrap_superadmin_email", mode="before")
    @classmethod
    def _norm_bootstrap_email(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("bootstrap_superadmin_password", mode="before")
    @classmethod
    def _strip_bootstrap_password(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return None
        if isinstance(v, str):
            return v.strip()
        return v

    # Origens CORS permitidas, separadas por vírgula. Use "*" só em desenvolvimento.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Assistente VigIA (xAI Grok ou API OpenAI-compatível)
    assist_llm_api_key: str | None = None
    assist_llm_base_url: str = "https://api.x.ai/v1"
    assist_llm_model: str = "grok-4-1-fast-reasoning"
    # Modelos opcionais por papel (padrão = assist_llm_model)
    assist_orch_model: str | None = None
    assist_sql_model: str | None = None

    # RAG — políticas SUAS (POST JSON: {"query": "...", "topK": N})
    kb_api_url: str | None = None
    kb_api_key: str | None = None
    kb_top_k: int = 3

    # Dicionário CADU (dicionariotudo.csv) para o assistente
    cadu_dictionary_path: str | None = None


settings = Settings()
