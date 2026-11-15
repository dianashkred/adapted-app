"""Application settings, read from environment variables (never from the repository)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # The application connects as a NON-superuser role (adapted_app -> app_write).
    database_url: str = "postgresql+psycopg://adapted_app:change-me@localhost:5432/adapted"
    # Migrations run as the schema owner (adapted_migrator -> admin).
    migrator_database_url: str = "postgresql+psycopg://adapted_migrator:change-me@localhost:5432/adapted"
    # Separate database for integration tests (same roles).
    test_database_url: str = "postgresql+psycopg://adapted_app:change-me@localhost:5432/adapted_test"
    test_migrator_database_url: str = "postgresql+psycopg://adapted_migrator:change-me@localhost:5432/adapted_test"
    test_analyst_database_url: str = "postgresql+psycopg://adapted_analyst:change-me@localhost:5432/adapted_test"

    # Personal-data protection (see docs/database.md, section 7).
    email_encryption_key: str = ""   # Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    email_hash_pepper: str = ""      # random secret used for HMAC-SHA256 of e-mails

    # Learning (decision 0002, rule 6): a revision quiz is offered after this many days of absence;
    # passed to the database function revision_offer(learner, course, absence_days).
    revision_absence_days: int = Field(default=7, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
