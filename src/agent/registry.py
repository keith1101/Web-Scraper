"""Tool Registry managing tool metadata, capabilities, statuses, and versioning."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Type


class ToolStatus(str, Enum):
    READY = "ready"
    UNTESTED = "untested"
    BROKEN = "broken"
    DEPRECATED = "deprecated"


@dataclass
class ToolMetadata:
    """Metadata schema representing a scraping or processing tool."""
    name: str
    version: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    status: ToolStatus = ToolStatus.UNTESTED
    last_tested: Optional[str] = None
    retry_policy: Dict[str, Any] = field(default_factory=lambda: {"max_retries": 3, "backoff": [2, 5, 10]})

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class ToolRegistry:
    """Central repository for discovery, inspection, and lifecycle management of tools."""

    def __init__(self):
        self._tools: Dict[str, Type[Any]] = {}
        self._metadata: Dict[str, ToolMetadata] = {}

    def register(self, tool_cls: Type[Any]) -> None:
        """Register a tool class and its metadata."""
        meta = getattr(tool_cls, "metadata", None)
        if not meta or not isinstance(meta, ToolMetadata):
            raise ValueError(f"Tool class {tool_cls.__name__} must define a valid ToolMetadata attribute 'metadata'")
        
        self._tools[meta.name] = tool_cls
        self._metadata[meta.name] = meta

    def get(self, name: str) -> Optional[Type[Any]]:
        """Retrieve tool class by name."""
        return self._tools.get(name)

    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        """Retrieve metadata for a tool by name."""
        return self._metadata.get(name)

    def list_tools(self) -> List[ToolMetadata]:
        """List metadata of all registered tools."""
        return list(self._metadata.values())

    def find_by_capability(self, capability: str) -> List[ToolMetadata]:
        """Find all tools possessing a given capability tag."""
        return [
            meta for meta in self._metadata.values()
            if capability.lower() in [c.lower() for c in meta.capabilities]
        ]

    def update_status(self, name: str, status: ToolStatus) -> None:
        """Update operational status and last_tested timestamp of a tool."""
        if name in self._metadata:
            self._metadata[name].status = status
            self._metadata[name].last_tested = datetime.now(timezone.utc).isoformat()

    def bump_version(self, name: str, part: str = "patch") -> str:
        """Increment tool semantic version (e.g. 1.0.0 -> 1.0.1)."""
        if name not in self._metadata:
            raise KeyError(f"Tool {name} not found in registry")
        
        current = self._metadata[name].version
        parts = [int(p) for p in current.split(".")]
        while len(parts) < 3:
            parts.append(0)

        if part == "major":
            parts[0] += 1
            parts[1] = 0
            parts[2] = 0
        elif part == "minor":
            parts[1] += 1
            parts[2] = 0
        else: # patch
            parts[2] += 1

        new_version = ".".join(map(str, parts))
        self._metadata[name].version = new_version
        return new_version

    def export_summary(self) -> Dict[str, Any]:
        """Export tool registry summary as JSON-serializable dictionary."""
        return {
            name: meta.to_dict()
            for name, meta in self._metadata.items()
        }


# Global tool registry singleton
registry = ToolRegistry()
