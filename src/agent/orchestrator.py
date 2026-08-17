"""Scraping Agent Orchestrator: Planner, State Machine, Tool Runner, and Recovery Manager."""

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.agent.registry import ToolStatus, registry
from src.agent.state import PipelinePhase, PipelineState, StateManager
from src.config import PipelineConfig
from src.tools.base import BaseTool, ToolExecutionResult
from src.utils.http_client import ErrorCategory, ResilientHttpClient
from src.utils.logging import AgentLogger

# Ensure all tools are registered
import src.tools  # noqa: F401


class ScrapingAgent:
    """Autonomous Orchestrator for the WordPress Scraping, Transformation, and Delivery Pipeline."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.config.ensure_directories()
        self.logger = AgentLogger(self.config.logs_dir)
        self.http_client = ResilientHttpClient(
            headers=self.config.headers,
            timeout=self.config.timeout,
            max_retries=self.config.max_retries,
            retry_delays=self.config.retry_delays,
        )
        self.state_manager = StateManager(self.config.state_file)
        self.state = self._initialize_state()

    def _initialize_state(self) -> PipelineState:
        """Load existing state if available, or create fresh PipelineState."""
        existing = self.state_manager.load()
        if existing:
            return existing

        fresh = PipelineState(source=self.config.source_url)
        self.state_manager.save(fresh)
        return fresh

    def _run_tool(self, tool_name: str, **kwargs) -> ToolExecutionResult:
        """Instantiate and execute a registered tool by name with state tracking."""
        tool_cls = registry.get(tool_name)
        if not tool_cls:
            err_msg = f"Tool '{tool_name}' is not registered in ToolRegistry"
            self.logger.error(err_msg)
            self.state_manager.record_error(self.state, tool_name, ErrorCategory.LOGIC_ERROR, err_msg)
            return ToolExecutionResult(tool_name, "unknown", False, error_type=ErrorCategory.LOGIC_ERROR, error_message=err_msg)

        tool_instance: BaseTool = tool_cls(
            config=self.config,
            http_client=self.http_client,
            logger=self.logger,
        )

        self.logger.info(f"Executing tool: [bold]{tool_name}[/bold] (v{tool_instance.metadata.version})...")
        result = tool_instance.run(**kwargs)

        if result.success:
            self.state_manager.record_completed_tool(self.state, tool_name)
        else:
            self.state_manager.record_error(
                self.state,
                tool_name,
                result.error_type or ErrorCategory.UNKNOWN_ERROR,
                result.error_message or "Tool execution failed",
            )

        return result

    def _import_existing_workspace_data(self) -> None:
        """Seed workspace from existing local files if present and workspace/raw is empty."""
        root_posts = Path("legacy/posts_public.json") if Path("legacy/posts_public.json").exists() else Path("posts_public.json")
        root_media = Path("legacy/media_public.json") if Path("legacy/media_public.json").exists() else Path("media_public.json")
        root_media_dir = Path("media")

        raw_posts = self.config.raw_dir / "posts_public.json"
        raw_media = self.config.raw_dir / "media_public.json"

        if not raw_posts.exists() and root_posts.exists():
            shutil.copy2(root_posts, raw_posts)
            self.logger.info(f"Imported existing {root_posts} into {raw_posts}")

        if not raw_media.exists() and root_media.exists():
            shutil.copy2(root_media, raw_media)
            self.logger.info(f"Imported existing {root_media} into {raw_media}")

        if root_media_dir.exists() and root_media_dir.is_dir():
            dest_media = self.config.workspace_media_dir
            for item in root_media_dir.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(root_media_dir)
                    target = dest_media / rel
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)

    def execute_pipeline(self, resume: bool = False, force_refresh: bool = False) -> bool:
        """
        Execute the entire scraping and packaging pipeline end-to-end.
        Supports resume mode from the last incomplete checkpoint.
        """
        if not resume:
            self.state = PipelineState(source=self.config.source_url)
            self.state_manager.save(self.state)

        self.logger.phase("1. ENVIRONMENT INSPECTION", "Validating workspace, connectivity, and configuration.")
        self.state_manager.update_phase(self.state, PipelinePhase.ENVIRONMENT_INSPECTION)
        self._import_existing_workspace_data()

        # Phase 2: Discovery
        if not resume or "discover_wordpress_api" not in self.state.completed_tools:
            self.logger.phase("2. DISCOVERY", "Inspecting /wp-json/ endpoints and capabilities.")
            self.state_manager.update_phase(self.state, PipelinePhase.DISCOVERY)
            disc_res = self._run_tool("discover_wordpress_api", base_url=self.config.source_url)
            if not disc_res.success:
                self.logger.warning("Discovery tool reported issues. Continuing with standard REST paths.")

        # Phase 3: Primary Extraction
        self.logger.phase("3. PRIMARY EXTRACTION", "Scraping posts, media metadata, categories, and tags.")
        self.state_manager.update_phase(self.state, PipelinePhase.PRIMARY_EXTRACTION)

        if not resume or "scrape_public_posts" not in self.state.completed_tools:
            posts_res = self._run_tool(
                "scrape_public_posts",
                base_url=self.config.source_url,
                per_page=self.config.per_page,
                force_refresh=force_refresh,
            )
            if not posts_res.success:
                self.state_manager.update_phase(self.state, PipelinePhase.FAILED)
                return False

        if not resume or "scrape_public_media" not in self.state.completed_tools:
            media_res = self._run_tool(
                "scrape_public_media",
                base_url=self.config.source_url,
                per_page=self.config.per_page,
                force_refresh=force_refresh,
            )
            if not media_res.success:
                self.state_manager.update_phase(self.state, PipelinePhase.FAILED)
                return False

        if not resume or "scrape_categories" not in self.state.completed_tools:
            self._run_tool("scrape_categories", base_url=self.config.source_url)

        if not resume or "scrape_tags" not in self.state.completed_tools:
            self._run_tool("scrape_tags", base_url=self.config.source_url)

        # Phase 4: Media Acquisition
        self.logger.phase("4. MEDIA ACQUISITION", "Downloading original media assets preserving YYYY/MM.")
        self.state_manager.update_phase(self.state, PipelinePhase.MEDIA_ACQUISITION)

        if not resume or "download_media" not in self.state.completed_tools:
            dl_res = self._run_tool("download_media")
            if not dl_res.success:
                self.logger.warning("Media download finished with partial errors. Proceeding to recovery.")

        # Phase 5: Normalization
        self.logger.phase("5. NORMALIZATION", "Converting raw outputs to stable schemas and post-media relationships.")
        self.state_manager.update_phase(self.state, PipelinePhase.NORMALIZATION)

        if not resume or "normalize_posts" not in self.state.completed_tools:
            p_res = self._run_tool("normalize_posts")
            if p_res.success:
                self.state_manager.update_statistics(self.state, {"posts": p_res.data.get("count", 0)})

        if not resume or "normalize_media" not in self.state.completed_tools:
            m_res = self._run_tool("normalize_media")
            if m_res.success:
                self.state_manager.update_statistics(self.state, {"media": m_res.data.get("count", 0)})

        if not resume or "extract_post_media" not in self.state.completed_tools:
            self._run_tool("extract_post_media")

        if not resume or "map_post_media" not in self.state.completed_tools:
            map_res = self._run_tool("map_post_media")
            if map_res.success:
                self.state_manager.update_statistics(self.state, {
                    "post_media_mappings": map_res.data.get("total_mappings", 0),
                    "featured_relations": map_res.data.get("featured_count", 0),
                    "content_relations": map_res.data.get("content_count", 0),
                    "attached_relations": map_res.data.get("attached_count", 0),
                })

        # Phase 6: Recovery
        self.logger.phase("6. RECOVERY & HEALTH AUDIT", "Validating local files, retrying missing media, and classifying errors.")
        self.state_manager.update_phase(self.state, PipelinePhase.RECOVERY)

        if not resume or "validate_media" not in self.state.completed_tools:
            self._run_tool("validate_media")

        if not resume or "recover_missing_media" not in self.state.completed_tools:
            rec_res = self._run_tool("recover_missing_media")
            if rec_res.success:
                self.state_manager.update_statistics(self.state, {
                    "missing_media": rec_res.data.get("unresolved_count", 0),
                    "external_media": rec_res.data.get("external_count", 0),
                })

        # Phase 7: Packaging
        self.logger.phase("7. PACKAGING", "Generating YYYY/MM/<post_id>-<slug>/ post packages.")
        self.state_manager.update_phase(self.state, PipelinePhase.PACKAGING)

        if not resume or "package_posts" not in self.state.completed_tools:
            pkg_res = self._run_tool("package_posts")
            if not pkg_res.success:
                self.state_manager.update_phase(self.state, PipelinePhase.FAILED)
                return False

        # Phase 8: Dataset Generation
        self.logger.phase("8. DATASET GENERATION", "Generating root/data master JSON and CSV files.")
        self.state_manager.update_phase(self.state, PipelinePhase.DATASET_GENERATION)

        if not resume or "generate_json" not in self.state.completed_tools:
            self._run_tool("generate_json")

        if not resume or "generate_csv" not in self.state.completed_tools:
            self._run_tool("generate_csv")

        # Phase 9: Report & Delivery Metadata
        self.logger.phase("9. REPORTING & METADATA", "Generating audit reports, manifest.json, and README.md.")
        self.state_manager.update_phase(self.state, PipelinePhase.REPORTING)

        if not resume or "generate_reports" not in self.state.completed_tools:
            self._run_tool("generate_reports")

        self.state_manager.update_phase(self.state, PipelinePhase.DELIVERY_METADATA)

        if not resume or "generate_manifest" not in self.state.completed_tools:
            self._run_tool("generate_manifest")

        if not resume or "generate_readme" not in self.state.completed_tools:
            self._run_tool("generate_readme")

        # Phase 10: Final Validation
        self.logger.phase("10. FINAL INTEGRITY VALIDATION", "Executing 12-point pre-delivery integrity checklist.")
        self.state_manager.update_phase(self.state, PipelinePhase.FINAL_VALIDATION)

        val_res = self._run_tool("validate_export")
        if not val_res.success or not val_res.data.get("all_passed", False):
            self.logger.error("Final export validation failed checklist checks.")
            self.state_manager.update_phase(self.state, PipelinePhase.FAILED)
            return False

        self.state_manager.update_phase(self.state, PipelinePhase.COMPLETED)
        self.logger.success("=================================================================")
        self.logger.success(" WordPress Scraping Agent Pipeline Completed Successfully!")
        self.logger.success(f" Customer Delivery Package is ready in: '{self.config.output_dir}'")
        self.logger.success("=================================================================")
        return True
