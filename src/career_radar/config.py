from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from career_radar.rules import offset_minutes


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr(
        "mysql+pymysql://careerradar:careerradar@127.0.0.1:3306/careerradar"
    )
    himalayas_api_key: SecretStr | None = None
    user_country: str = Field(default="ZW", pattern=r"^[A-Z]{2}$")
    user_utc_offset: str = Field(default="UTC+02:00", pattern=r"^UTC[+-]\d{1,2}(:\d{2})?$")
    source_sync_enabled: bool = False
    request_timeout: float = Field(default=20, gt=0, le=120)
    max_requests: int = Field(default=500, ge=1, le=10000)
    max_pages: int = Field(default=20, ge=1, le=1000)
    max_queries: int = Field(default=100, ge=1, le=1000)
    max_retries: int = Field(default=3, ge=0, le=5)
    max_retry_wait: float = Field(default=60, gt=0, le=300)
    request_interval: float = Field(default=1.1, ge=0)
    verification_budget: int = Field(default=50, ge=0, le=1000)
    verification_max_age_hours: int = Field(default=24, ge=1)
    criteria_path: str | None = None

    @field_validator("user_utc_offset")
    @classmethod
    def valid_offset(cls, value):
        offset_minutes(value)
        return value
