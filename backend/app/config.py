"""Application configuration, read from environment variables (.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App metadata DB
    database_url: str = "postgresql://postgres:postgres@localhost:5432/dbeelight"

    # LLM
    openai_api_key: str = ""
    llm_model: str = "gpt-5.2"
    router_model: str = "gpt-5.2"

    # Excel MCP server (HTTP)
    excel_mcp_url: str = "http://localhost:8931/mcp"

    # Storage
    data_root: str = "./_data"
    sqlite_allowed_dirs: str = "./_data/databases:./_data/temp_dbs"

    # Auth (cookie session)
    google_client_id: str = ""
    google_client_secret: str = ""
    session_secret: str = "dev-session-secret-change-me"
    session_same_site: str = "lax"
    session_https_only: bool = False
    frontend_url: str = "http://localhost:5173"
    public_base_url: str = ""  # if set, used as the redirect_uri base for Google OAuth

    # Tool loop
    tool_result_max_tokens: int = 4000
    max_tool_iterations: int = 10

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def databases_dir(self) -> Path:
        return Path(self.data_root) / "databases"

    @property
    def temp_dbs_dir(self) -> Path:
        return Path(self.data_root) / "temp_dbs"

    @property
    def allowed_dirs(self) -> list[Path]:
        return [Path(p).resolve() for p in self.sqlite_allowed_dirs.split(":") if p.strip()]

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.databases_dir.mkdir(parents=True, exist_ok=True)
    s.temp_dbs_dir.mkdir(parents=True, exist_ok=True)
    return s
