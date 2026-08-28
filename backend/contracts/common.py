"""Strict reusable contract primitives."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)

    @field_validator("*", mode="after")
    @classmethod
    def require_utc_for_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must include a UTC offset")
            if value.utcoffset().total_seconds() != 0:
                raise ValueError("timestamps must be transported in UTC")
        return value
