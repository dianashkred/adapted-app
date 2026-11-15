from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://adapted_app:change-me@localhost:5432/adapted"
    migrator_database_url: str = "postgresql+psycopg://adapted_migrator:change-me@localhost:5432/adapted"
    test_database_url: str = "postgresql+psycopg://adapted_app:change-me@localhost:5432/adapted_test"
    test_migrator_database_url: str = "postgresql+psycopg://adapted_migrator:change-me@localhost:5432/adapted_test"
    test_analyst_database_url: str = "postgresql+psycopg://adapted_analyst:change-me@localhost:5432/adapted_test"

    email_encryption_key: str = ""
    email_hash_pepper: str = ""

    revision_absence_days: int = Field(default=7, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
