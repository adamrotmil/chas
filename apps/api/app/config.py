from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./charlesops.local.sqlite"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001,http://localhost:3002,http://127.0.0.1:3002,http://localhost:3003,http://127.0.0.1:3003"
    storage_root: str = "/app/storage"
    object_storage_provider: str = "local"
    gcs_bucket: str = ""
    gcs_prefix: str = "charlesops"
    openai_api_key: str = ""
    openai_project_id: str = ""
    vision_model: str = "gpt-4.1-mini"
    vision_live_calls_enabled: bool = False
    text_generation_model: str = "gpt-5.5"
    text_generation_reasoning_effort: str = "medium"
    text_generation_live_calls_enabled: bool = False
    chat_reasoning_effort: str = "medium"
    chat_require_live_model: bool = False
    embedding_model: str = "text-embedding-3-small"
    embedding_live_calls_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
