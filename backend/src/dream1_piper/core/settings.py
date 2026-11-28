from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSTACK_",
        env_file=PROJECT_ROOT / ".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "dream1-piper station API"
    environment: str = "development"
    ui_host: str = "127.0.0.1"
    ui_port: int = 8443
    ui_operator_token: SecretStr | None = None
    worker_token: SecretStr | None = None
    ui_ca_cert: str | None = None
    session_secret: SecretStr = SecretStr("")
    session_ttl_seconds: int = 28800
    storage_backend: Literal["postgres", "memory"] = "postgres"
    memory_history_limit: int = 100000
    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://dream1_piper:dream1_piper@127.0.0.1:5432/dream1_piper"
        ),
        validation_alias="DATABASE_URL",
    )
    station_ws_host: str = "127.0.0.1"
    station_ws_port: int = 8765
    ros_bridge_url: str = "ws://127.0.0.1:8766"
    dream_mode: str = "action"
    dream_checkpoint: str = "dreamlabs/dream-1-beta"
    dream_task: str | None = None
    cors_origins: list[str] = Field(default_factory=list)
    frontend_dist: str = str(PROJECT_ROOT / "frontend/dist")
    control_hz: int = 20
    teleop_max_hz: int = 30
    teleop_linear_limit_m_s: float = 0.05
    teleop_angular_limit_rad_s: float = 0.25
    teleop_deadman_timeout_ms: int = 250
    metrics_queue_size: int = 10000
    metrics_retention_days: int = 30
    events_heartbeat_seconds: float = 15.0
    ui_tls_cert: str | None = None
    ui_tls_key: str | None = None
    camera_left_device: str | None = None
    camera_top_device: str | None = None
    camera_right_device: str | None = None
    robot_config: str = str(PROJECT_ROOT / "configs/app_robot.yaml")
    dream_config: str = str(PROJECT_ROOT / "experiments/piper_station_worker/config/dream.yaml")
    can_left: str | None = None
    can_right: str | None = None

    def validate_deployment(self):
        if not 1 <= self.memory_history_limit <= 100000:
            raise ValueError("RSTACK_MEMORY_HISTORY_LIMIT must be between 1 and 100000")
        if self.events_heartbeat_seconds <= 0:
            raise ValueError("RSTACK_EVENTS_HEARTBEAT_SECONDS must be greater than 0")
        if self.environment != "production":
            return
        if self.storage_backend == "memory":
            raise ValueError("RSTACK_STORAGE_BACKEND=memory is not allowed in production")
        if not self.ui_operator_token or not self.ui_operator_token.get_secret_value():
            raise ValueError("RSTACK_UI_OPERATOR_TOKEN is required in production")
        if len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("RSTACK_SESSION_SECRET must contain at least 32 characters")
        if not self.ui_tls_cert or not self.ui_tls_key:
            raise ValueError("RSTACK_UI_TLS_CERT and RSTACK_UI_TLS_KEY are required in production")
        if not self.worker_token or len(self.worker_token.get_secret_value()) < 32:
            raise ValueError("RSTACK_WORKER_TOKEN must contain at least 32 characters")


@lru_cache
def get_settings() -> Settings:
    return Settings()
