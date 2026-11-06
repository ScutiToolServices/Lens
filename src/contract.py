"""Shared HTTP/MCP request and result schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Mode = Literal["fast", "accurate"]
Region = tuple[StrictInt, StrictInt, StrictInt, StrictInt]


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    file_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    mode: Mode = Field(default="accurate", description="fast: standard CPU model; accurate: tessdata_best (default)")
    regions: list[Region] = Field(default_factory=list, max_length=256)
    preprocess: bool = False


class UploadResult(BaseModel):
    file_id: str
    width: int
    height: int
    size_bytes: int
    expires_at: float
    message: str


class RegionResult(BaseModel):
    index: int
    region: Region
    text: str
    confidence: float | None


class ExtractResult(BaseModel):
    file_id: str
    mode: Mode
    model: str
    regions: list[RegionResult]
    text: str
    cached: bool
    message: str
