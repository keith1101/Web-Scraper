"""Structured logging for tool executions, pipeline events, and terminal output."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from rich.console import Console
from rich.theme import Theme

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "phase": "bold magenta",
})

console = Console(theme=custom_theme)


class AgentLogger:
    """Handles structured JSON log recording and formatted console display."""

    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.logs_dir / "tool_executions.jsonl"

    def _get_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_tool_execution(
        self,
        tool_name: str,
        version: str,
        inputs: Dict[str, Any],
        status: str,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        error_type: Optional[str] = None,
        attempt: int = 1,
    ) -> None:
        """Record structured JSON log entry for a tool run."""
        record = {
            "timestamp": self._get_timestamp(),
            "tool": tool_name,
            "version": version,
            "attempt": attempt,
            "status": status,
            "inputs": inputs,
            "output": output or {},
        }
        if error:
            record["error"] = error
        if error_type:
            record["error_type"] = error_type

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def info(self, message: str) -> None:
        console.print(f"[info][INFO][/info] {message}")

    def success(self, message: str) -> None:
        console.print(f"[success][SUCCESS][/success] {message}")

    def warning(self, message: str) -> None:
        console.print(f"[warning][WARNING][/warning] {message}")

    def error(self, message: str) -> None:
        console.print(f"[error][ERROR][/error] {message}")

    def phase(self, phase_name: str, description: str = "") -> None:
        console.print()
        console.rule(f"[phase]PHASE: {phase_name}[/phase]")
        if description:
            console.print(f"[italic]{description}[/italic]\n")
