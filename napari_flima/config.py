from typing import List, Dict, Optional
from pydantic import BaseModel, Field
import yaml


class IntroConfig(BaseModel):
    flim_type: str = "TCSPC FLIM"
    laser_frequency: int = 80
    harmonic: int = 1
    g_offset: float = 32767.5
    s_offset: float = 32767.5
    stack_size: int = 5
    num_channels: int = 1
    channel_assignments: List[str] = Field(default_factory=lambda: ["Intensity"])
    calculate_gs: bool = True


class SingleFileConfig(BaseModel):
    file_name: str
    group: str = "None"
    mask_layer: str = "None"
    threshold_lower: int = 0
    threshold_upper: int = 4095


class FileSelectionConfig(BaseModel):
    known_groups: List[str] = Field(
        default_factory=lambda: ["None", "Condition 1", "Condition 2"]
    )
    files: Dict[str, SingleFileConfig] = Field(default_factory=dict)


class CursorConfig(BaseModel):
    active: bool = True
    color: str = "red"
    radius: float = 0.05
    g_value: float = 0.0
    s_value: float = 0.0
    tau_m: float = 0.0
    tau_p: float = 0.0


class SegmentationConfig(BaseModel):
    min_size: int = 50
    threshold: int = 75
    iou_threshold: float = 0.3
    max_dist: int = 10
    min_persist: int = 30


class ReportConfig(BaseModel):
    export_intensity: bool = True
    export_flim: bool = True
    export_gs: bool = True
    export_downstream: bool = False
    comparison_group: Optional[str] = None
    export_directory: Optional[str] = None


class DownstreamConfig(BaseModel):
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    cursors: List[CursorConfig] = Field(default_factory=list)
    report: ReportConfig = Field(default_factory=ReportConfig)


class FLIMAnalysisConfig(BaseModel):
    intro: IntroConfig = Field(default_factory=IntroConfig)
    file_selection: FileSelectionConfig = Field(default_factory=FileSelectionConfig)
    downstream: DownstreamConfig = Field(default_factory=DownstreamConfig)


def load_config_from_yaml(file_path: str) -> FLIMAnalysisConfig:
    """Load and parse FLIM analysis configuration from a YAML file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        data = {}
    return FLIMAnalysisConfig.model_validate(data)


def save_config_to_yaml(config: FLIMAnalysisConfig, file_path: str) -> None:
    """Save FLIM analysis configuration to a YAML file."""
    data = config.model_dump()
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
