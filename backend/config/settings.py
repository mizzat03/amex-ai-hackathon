"""One typed surface for implementation-owned, versioned demo defaults."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with conservative hackathon defaults, not production claims."""

    model_config = SettingsConfigDict(
        # Secrets are supplied by the process environment (Compose may populate
        # that environment). Application code never opens secret-bearing files.
        env_file=None,
        env_prefix="AMEX_",
        extra="ignore",
        case_sensitive=False,
    )

    configuration_version: str = "demo-config.v1"
    environment: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    simulator_host: str = "127.0.0.1"
    simulator_port: int = Field(default=8010, ge=1, le=65535)
    simulator_url: str = "http://localhost:8010"
    ingestion_host: str = "127.0.0.1"
    ingestion_port: int = Field(default=8020, ge=1, le=65535)
    simulator_tick_seconds: float = Field(default=1.0, ge=0.1, le=30)
    simulator_batch_size: int = Field(default=250, ge=10, le=5000)
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ]
    redis_url: str = "redis://localhost:6379/0"
    postgres_dsn: str = "postgresql://amex:amex@localhost:5432/amex_incidents"
    payment_stream: str = "amex:synthetic:payment-events:v1"
    operational_stream: str = "amex:synthetic:operational-events:v1"
    ingestion_claim_idle_ms: int = Field(default=5_000, ge=0, le=300_000)
    demo_seed: int = 20260827
    copilot_provider: str = "disabled"
    copilot_model: str = ""
    copilot_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    copilot_initial_max_output_tokens: int = Field(default=1800, ge=256, le=8192)
    copilot_follow_up_max_output_tokens: int = Field(default=1100, ge=256, le=8192)
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "AMEX_OPENAI_API_KEY"),
        exclude=True,
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "AMEX_ANTHROPIC_API_KEY"),
        exclude=True,
    )
    openai_endpoint: str = "https://api.openai.com/v1/responses"
    anthropic_endpoint: str = "https://api.anthropic.com/v1/messages"

    bucket_duration_seconds: int = Field(default=10, ge=1)
    current_window_seconds: int = Field(default=60, ge=10)
    baseline_window_seconds: int = Field(default=300, ge=60)
    allowed_lateness_seconds: int = Field(default=15, ge=0)
    telemetry_stale_after_seconds: int = Field(default=30, ge=1)
    baseline_required_samples: int = Field(default=1200, ge=100)
    min_current_attempts: int = Field(default=150, ge=1)
    min_baseline_attempts: int = Field(default=600, ge=1)
    min_current_technical_errors: int = Field(default=8, ge=1)
    anomaly_alpha: float = Field(default=0.01, gt=0, lt=0.5)
    min_absolute_error_rate_increase: float = Field(default=0.02, gt=0, lt=1)
    detection_persistence_buckets: int = Field(default=2, ge=1)
    recovery_persistence_buckets: int = Field(default=4, ge=2)
    recovery_alpha: float = Field(default=0.05, gt=0, lt=0.5)
    recovery_residual_margin: float = Field(default=0.005, ge=0, lt=1)
    recovery_absolute_safety_ceiling: float = Field(default=0.02, gt=0, lt=1)
    latency_min_absolute_increase_ms: float = Field(default=50.0, gt=0)
    latency_min_relative_increase: float = Field(default=0.50, gt=0)
    cooldown_seconds: int = Field(default=60, ge=0)

    dimension_min_current_attempts: int = Field(default=30, ge=1)
    dimension_min_baseline_attempts: int = Field(default=100, ge=1)
    dimension_min_current_errors: int = Field(default=5, ge=1)
    dimension_min_excess_errors: float = Field(default=3.0, ge=0)
    dimension_min_rate_increase: float = Field(default=0.03, ge=0, lt=1)
    dimension_seed_top_n: int = Field(default=3, ge=1, le=10)
    dimension_child_excess_retention: float = Field(default=0.65, gt=0, le=1)
    dimension_concentration_improvement: float = Field(default=0.10, ge=0, le=1)

    rca_lookback_seconds: int = Field(default=900, ge=60)
    rca_clock_skew_seconds: int = Field(default=15, ge=0)
    rca_shortlist_size: int = Field(default=3, ge=1, le=10)
    recent_raw_event_retention_seconds: int = Field(default=900, ge=60)
    incident_page_size: int = Field(default=25, ge=1, le=100)
    metric_history_max_points: int = Field(default=600, ge=10, le=5000)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
