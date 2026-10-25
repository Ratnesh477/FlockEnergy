from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class GeoLocation(BaseModel):
    """Geographic coordinate representation."""
    latitude: float = Field(..., description="WGS84 latitude coordinate in decimal degrees")
    longitude: float = Field(..., description="WGS84 longitude coordinate in decimal degrees")


class HierarchyNode(BaseModel):
    """Individual network topology node in the distribution hierarchy."""
    code: str = Field(..., description="Unique alphanumeric identifier for the node (e.g. Z-01, DT-001)")
    name: str = Field(..., description="Human-readable name of the node (e.g. Jaipur Zone 1)")
    is_healed: bool = Field(
        default=False, 
        description="True if an incomplete or missing value in legacy data was automatically repaired"
    )


class MeterHierarchy(BaseModel):
    """Full 7-tier distribution hierarchy chain for a meter."""
    zone: HierarchyNode
    circle: HierarchyNode
    division: HierarchyNode
    subdivision: HierarchyNode
    substation: HierarchyNode
    feeder: HierarchyNode
    dt: HierarchyNode


class MeterSummary(BaseModel):
    """Compact summary schema for a smart meter."""
    meter_id: str = Field(..., description="Unique utility meter identifier (e.g. J100000)")
    serial_number: str = Field(..., description="Hardware manufacturer serial number")
    make: str = Field(..., description="Meter manufacturer (e.g. HPL, Genus, L&T, Secure, Allied)")
    phase_type: str = Field(..., description="Phase configuration ('single' or 'three')")
    install_status: str = Field(..., description="Operational status ('Installed', 'Faulty', 'Decommissioned')")
    dt_code: str = Field(..., description="Distribution transformer code to which the meter is connected")
    build: Optional[str] = Field(default=None, description="Firmware / legacy build generation ('legacy' or 'v2')")


class MeterDetail(MeterSummary):
    """Detailed meter information including nameplate specs, coordinates, and network location."""
    install_type: Optional[str] = Field(default=None, description="Metering setup type (e.g. 'Whole Current', 'CT Operated')")
    geo: Optional[GeoLocation] = Field(default=None, description="Meter GPS coordinates")
    hierarchy: Optional[MeterHierarchy] = Field(default=None, description="Full 7-level grid hierarchy")
    nameplate: Optional[dict[str, str]] = Field(
        default=None, 
        description="Normalized key-value mapping of all physical and operational parameters"
    )


class ConsumptionReading(BaseModel):
    """Normalized 30-minute interval smart meter consumption record."""
    timestamp: str = Field(..., description="Standardized ISO 8601 timestamp with timezone offset")
    raw_timestamp: str = Field(..., description="Original raw legacy timestamp (DD/MM/YYYY HH:mm)")
    kwh: float = Field(..., description="Cumulative active energy in kilowatt-hours (kWh)")
    kvah: float = Field(..., description="Cumulative apparent energy in kilovolt-ampere-hours (kVAh)")
    volt_r: float = Field(..., description="R-phase voltage in Volts (V)")


class ConsumptionStats(BaseModel):
    """Summary metrics and statistical aggregations for consumption history."""
    reading_count: int = Field(..., description="Total number of reading intervals returned")
    start_time: Optional[str] = Field(default=None, description="Timestamp of oldest reading in interval")
    end_time: Optional[str] = Field(default=None, description="Timestamp of newest reading in interval")
    kwh_initial: float = Field(..., description="Starting active energy index")
    kwh_latest: float = Field(..., description="Latest active energy index")
    kwh_total_consumed: float = Field(..., description="Net energy consumed over the recording window (latest - initial)")
    avg_voltage: float = Field(..., description="Average R-phase voltage across all intervals")
    min_voltage: float = Field(..., description="Minimum recorded R-phase voltage")
    max_voltage: float = Field(..., description="Maximum recorded R-phase voltage")


class MeterConsumptionResponse(BaseModel):
    """Response payload for smart meter consumption history."""
    meter_id: str = Field(..., description="Meter ID for the requested consumption data")
    readings: list[ConsumptionReading] = Field(..., description="Chronological series of consumption readings")
    stats: ConsumptionStats = Field(..., description="Calculated consumption and voltage analytics")


class TransformerSummary(BaseModel):
    """Summary information for a distribution transformer (DT)."""
    code: str = Field(..., description="Unique DT code (e.g. DT-001)")
    name: str = Field(..., description="DT descriptive location name")
    feeder_code: str = Field(..., description="Parent feeder code (e.g. F-001)")
    capacity_kva: float = Field(..., description="Rated transformer capacity in kVA")
    meter_count: int = Field(default=0, description="Total number of meters connected to this transformer")


class TransformerDetail(TransformerSummary):
    """Detailed DT info including attached meters and status breakdown."""
    installed_count: int = Field(default=0, description="Count of currently active/installed meters")
    faulty_count: int = Field(default=0, description="Count of meters flagged as faulty")
    decommissioned_count: int = Field(default=0, description="Count of decommissioned meters")
    meters: list[MeterSummary] = Field(default_factory=list, description="List of connected smart meters")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standardized envelope for paginated responses."""
    data: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class HierarchyTreeNode(BaseModel):
    """Recursive node structure representing the distribution grid tree."""
    code: str
    name: str
    level: str
    meter_count: int = 0
    children: list["HierarchyTreeNode"] = Field(default_factory=list)


class AnalyticsSummary(BaseModel):
    """System-wide operational analytics and grid overview."""
    total_meters: int
    by_status: dict[str, int]
    by_make: dict[str, int]
    by_phase: dict[str, int]
    by_build: dict[str, int]
    total_transformers: int
    total_transformer_capacity_kva: float
    healed_hierarchy_anomalies: int
    last_synced_at: str


class LoginRequest(BaseModel):
    """Explicit authentication request payload."""
    username: Optional[str] = Field(default=None, description="Username or email (defaults to configured service account)")
    password: Optional[str] = Field(default=None, description="Password (defaults to configured service password)")


class AuthStatusResponse(BaseModel):
    """Current session status and cookie lifecycle info."""
    authenticated: bool
    session_token_present: bool
    portal_url: str
    account_email: str
