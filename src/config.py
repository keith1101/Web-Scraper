"""Configuration settings for the WordPress Scraping Agent."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import os
import dotenv

dotenv.load_dotenv()


@dataclass
class PipelineConfig:
    """Central configuration for agent execution and directory layout."""

    # Target WordPress site
    source_url: str = os.getenv("WP_SOURCE_URL", "https://abi.com.vn").rstrip("/")

    # Optional authentication
    wp_username: Optional[str] = os.getenv("WP_USERNAME")
    wp_app_password: Optional[str] = os.getenv("WP_APP_PASSWORD")

    # Directory Paths
    workspace_dir: Path = Path("workspace")
    output_dir: Path = Path("output")

    # HTTP & Scraping Settings
    per_page: int = 100
    timeout: int = 45
    max_retries: int = 3
    retry_delays: List[float] = field(default_factory=lambda: [2.0, 5.0, 10.0])
    
    # Headers
    headers: Dict[str, str] = field(default_factory=lambda: {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    })

    # Internal Workspace Paths
    @property
    def raw_dir(self) -> Path:
        return self.workspace_dir / "raw"

    @property
    def normalized_dir(self) -> Path:
        return self.workspace_dir / "normalized"

    @property
    def workspace_media_dir(self) -> Path:
        return self.workspace_dir / "media"

    @property
    def discovery_dir(self) -> Path:
        return self.workspace_dir / "discovery"

    @property
    def state_dir(self) -> Path:
        return self.workspace_dir / "state"

    @property
    def logs_dir(self) -> Path:
        return self.workspace_dir / "logs"

    @property
    def temp_dir(self) -> Path:
        return self.workspace_dir / "temp"

    # Delivery Output Paths
    @property
    def data_dir(self) -> Path:
        return self.output_dir / "data"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "manifest.json"

    @property
    def readme_path(self) -> Path:
        return self.output_dir / "README.md"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "run_context.json"

    def ensure_directories(self) -> None:
        """Create required internal and output directories if they do not exist."""
        for p in [
            self.raw_dir,
            self.normalized_dir,
            self.workspace_media_dir,
            self.discovery_dir,
            self.state_dir,
            self.logs_dir,
            self.temp_dir,
            self.data_dir,
            self.reports_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)
