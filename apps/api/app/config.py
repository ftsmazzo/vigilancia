from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://vigsocial:vigsocial_dev@localhost:5432/vigsocial"
    redis_url: str = "redis://localhost:6379/0"
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


settings = Settings()
