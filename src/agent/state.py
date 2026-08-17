"""Persistent pipeline state manager and run checkpointing."""

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class PipelinePhase(str, Enum):
    INITIALIZED = "INITIALIZED"
    ENVIRONMENT_INSPECTION = "ENVIRONMENT_INSPECTION"
    DISCOVERY = "DISCOVERY"
    PRIMARY_EXTRACTION = "PRIMARY_EXTRACTION"
    MEDIA_ACQUISITION = "MEDIA_ACQUISITION"
    NORMALIZATION = "NORMALIZATION"
    RECOVERY = "RECOVERY"
    PACKAGING = "PACKAGING"
    DATASET_GENERATION = "DATASET_GENERATION"
    REPORTING = "REPORTING"
    DELIVERY_METADATA = "DELIVERY_METADATA"
    FINAL_VALIDATION = "FINAL_VALIDATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class PipelineState:
    """Represents full persistent runtime state of the scraping pipeline."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str = ""
    phase: PipelinePhase = PipelinePhase.INITIALIZED
    completed_tools: List[str] = field(default_factory=list)
    pending_tools: List[str] = field(default_factory=list)
    statistics: Dict[str, int] = field(default_factory=lambda: {
        "posts": 0,
        "media": 0,
        "post_media_mappings": 0,
        "featured_relations": 0,
        "content_relations": 0,
        "attached_relations": 0,
        "missing_media": 0,
        "external_media": 0,
        "download_errors": 0,
    })
    errors: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.phase.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineState":
        copy_data = dict(data)
        if "phase" in copy_data and isinstance(copy_data["phase"], str):
            copy_data["phase"] = PipelinePhase(copy_data["phase"])
        return cls(**copy_data)


class StateManager:
    """Manages persistent reading and atomic writing of PipelineState."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Optional[PipelineState]:
        """Load state from file if exists and valid."""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return PipelineState.from_dict(data)
        except Exception:
            return None

    def save(self, state: PipelineState) -> None:
        """Atomically persist state to disk."""
        state.updated_at = datetime.now(timezone.utc).isoformat()
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        if self.state_file.exists():
            self.state_file.unlink()
        temp_file.rename(self.state_file)

    def update_phase(self, state: PipelineState, phase: PipelinePhase) -> None:
        """Transition pipeline phase and save checkpoint."""
        state.phase = phase
        self.save(state)

    def record_completed_tool(self, state: PipelineState, tool_name: str) -> None:
        """Mark tool execution complete."""
        if tool_name not in state.completed_tools:
            state.completed_tools.append(tool_name)
        if tool_name in state.pending_tools:
            state.pending_tools.remove(tool_name)
        self.save(state)

    def record_error(
        self,
        state: PipelineState,
        tool_name: str,
        error_type: str,
        message: str,
        retryable: bool = False,
    ) -> None:
        """Append error entry to runtime state and save."""
        error_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "error_type": error_type,
            "message": message,
            "retryable": retryable,
        }
        state.errors.append(error_entry)
        self.save(state)

    def update_statistics(self, state: PipelineState, stats: Dict[str, int]) -> None:
        """Update runtime statistical counters."""
        state.statistics.update(stats)
        self.save(state)
