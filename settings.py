from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Travel Planner Multi-Agent")
    app_version: str = Field(default="2.1.0")
    app_env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    mcp_12306_http_url: str = Field(default="")
    amap_maps_api_key: str = Field(default="")
    amap_key: str = Field(default="")

    llm_base_url: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="deepseek-chat")

    api_key_enabled: bool = Field(default=False)
    api_key_value: str = Field(default="")

    redis_url: str = Field(default="")
    redis_prefix: str = Field(default="travel:session:")

    rate_limit_enabled: bool = Field(default=False)
    rate_limit_requests: int = Field(default=30)
    rate_limit_window_seconds: int = Field(default=60)
    rate_limit_whitelist: str = Field(default="127.0.0.1,::1")


settings = AppSettings()
