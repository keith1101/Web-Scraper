"""BaseTool abstract class and execution wrapper."""

import abc
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.config import PipelineConfig
from src.utils.http_client import ErrorCategory, ResilientHttpClient
from src.utils.logging import AgentLogger


@dataclass
class ToolExecutionResult:
    """Standardized output returned by every tool run."""
    tool_name: str
    version: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    attempt: int = 1


class BaseTool(abc.ABC):
    """Abstract base class for all scraping, processing, packaging, and validation tools."""

    metadata: ToolMetadata

    def __init__(
        self,
        config: PipelineConfig,
        http_client: Optional[ResilientHttpClient] = None,
        logger: Optional[AgentLogger] = None,
    ):
        self.config = config
        self.http_client = http_client or ResilientHttpClient(
            headers=config.headers,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_delays=config.retry_delays,
        )
        self.logger = logger or AgentLogger(config.logs_dir)

    def run(self, **kwargs) -> ToolExecutionResult:
        """Safe execution wrapper with validation, logging, and error categorization."""
        tool_name = self.metadata.name
        version = self.metadata.version

        try:
            self._validate_inputs(**kwargs)
            result_data = self._execute(**kwargs)
            self._validate_outputs(result_data)

            # Update registry status
            registry.update_status(tool_name, ToolStatus.READY)

            self.logger.log_tool_execution(
                tool_name=tool_name,
                version=version,
                inputs=kwargs,
                status="success",
                output=result_data,
            )

            return ToolExecutionResult(
                tool_name=tool_name,
                version=version,
                success=True,
                data=result_data,
            )

        except Exception as exc:
            tb = traceback.format_exc()
            error_type = getattr(exc, "error_type", ErrorCategory.LOGIC_ERROR)
            error_msg = str(exc)

            # If it's a known schema or logic issue, mark status in registry
            registry.update_status(tool_name, ToolStatus.BROKEN)

            self.logger.log_tool_execution(
                tool_name=tool_name,
                version=version,
                inputs=kwargs,
                status="failed",
                error=f"{error_msg}\n{tb}",
                error_type=error_type,
            )

            self.logger.error(f"[{tool_name}] Failed: {error_msg}")

            return ToolExecutionResult(
                tool_name=tool_name,
                version=version,
                success=False,
                error_type=error_type,
                error_message=error_msg,
            )

    def _validate_inputs(self, **kwargs) -> None:
        """Validate input parameters against metadata schema. Default checks required keys."""
        required_keys = self.metadata.input_schema.get("required", [])
        for key in required_keys:
            if key not in kwargs or kwargs[key] is None:
                err = ValueError(f"Missing required input parameter: '{key}' for tool '{self.metadata.name}'")
                setattr(err, "error_type", ErrorCategory.SCHEMA_ERROR)
                raise err

    def _validate_outputs(self, result: Dict[str, Any]) -> None:
        """Validate result dictionary against output schema."""
        if not isinstance(result, dict):
            err = ValueError(f"Tool '{self.metadata.name}' must return a dictionary result")
            setattr(err, "error_type", ErrorCategory.SCHEMA_ERROR)
            raise err

    @abc.abstractmethod
    def _execute(self, **kwargs) -> Dict[str, Any]:
        """Core tool logic to be implemented by child classes."""
        raise NotImplementedError
