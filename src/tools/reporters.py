"""Reporting tools for generating audit CSV reports and human-readable migration summaries."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool


class GenerateReportsTool(BaseTool):
    """Tool: generate_reports (Tool 16)"""

    metadata = ToolMetadata(
        name="generate_reports",
        version="1.0.0",
        description="Generates missing media, external media, error CSVs, and migration_summary.txt in reports/.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "missing_media_csv": {"type": "string"},
                "external_media_csv": {"type": "string"},
                "download_errors_csv": {"type": "string"},
                "summary_txt": {"type": "string"},
            },
        },
        capabilities=["reporting", "audit", "csv", "summary"],
        dependencies=["recover_missing_media", "map_post_media"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        reports_dir = self.config.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)

        rec_path = self.config.state_dir / "recovery_report.json"
        unresolved_records = []
        external_records = []
        download_errors = []

        if rec_path.exists():
            with open(rec_path, "r", encoding="utf-8") as f:
                rec_data = json.load(f)
                unresolved_records = rec_data.get("unresolved_records", [])
                external_records = rec_data.get("external_records", [])
                download_errors = rec_data.get("download_errors", [])

        # 1. missing_media.csv
        missing_csv_path = reports_dir / "missing_media.csv"
        with open(missing_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["post_id", "media_id", "relation", "source_url", "status", "reason"]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in unresolved_records:
                writer.writerow(r)

        # 2. external_media.csv
        external_csv_path = reports_dir / "external_media.csv"
        with open(external_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["post_id", "url", "domain", "download_status", "local_file", "reason"]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in external_records:
                writer.writerow(r)

        # 3. download_errors.csv
        errors_csv_path = reports_dir / "download_errors.csv"
        with open(errors_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["media_id", "source_url", "status", "reason"]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in download_errors:
                writer.writerow(r)

        # 4. migration_summary.txt
        posts_path = self.config.normalized_dir / "posts.json"
        media_path = self.config.normalized_dir / "media.json"
        mapping_path = self.config.normalized_dir / "post_media_mapping.json"

        post_count = 0
        media_count = 0
        mapping_count = 0
        featured_count = 0
        content_count = 0
        attached_count = 0

        if posts_path.exists():
            with open(posts_path, "r", encoding="utf-8") as f:
                post_count = len(json.load(f))
        if media_path.exists():
            with open(media_path, "r", encoding="utf-8") as f:
                media_count = len(json.load(f))
        if mapping_path.exists():
            with open(mapping_path, "r", encoding="utf-8") as f:
                mappings = json.load(f)
                mapping_count = len(mappings)
                featured_count = sum(1 for m in mappings if "featured" in m.get("relations", []))
                content_count = sum(1 for m in mappings if "content" in m.get("relations", []))
                attached_count = sum(1 for m in mappings if "attached" in m.get("relations", []))

        summary_txt_path = reports_dir / "migration_summary.txt"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        summary_content = f"""======================================================================
WORDPRESS SCRAPING & MIGRATION SUMMARY
Generated at: {now_str}
Source Site: {self.config.source_url}
======================================================================

1. DATASET STATISTICS
----------------------------------------------------------------------
Total Published Posts:        {post_count}
Total Media Assets:           {media_count}
Total Post-Media Mappings:    {mapping_count}
  - Featured Relations:       {featured_count}
  - Content Relations:        {content_count}
  - Attachment Relations:     {attached_count}

2. ASSET & INTEGRITY AUDIT
----------------------------------------------------------------------
Missing/Unresolved Media:     {len(unresolved_records)}
External Domain References:   {len(external_records)}
Direct Download Errors:       {len(download_errors)}

3. DELIVERY PACKAGING DETAILS
----------------------------------------------------------------------
Canonical Datasets:           root/data/ (JSON + CSV)
Per-Post Directory Layout:    root/YYYY/MM/<post_id>-<slug>/
Audit Reports:                root/reports/
Manifest & Documentation:     root/manifest.json, root/README.md

4. RECOMMENDED NEXT STEPS
----------------------------------------------------------------------
- Review reports/missing_media.csv for broken WordPress media references.
- Review reports/external_media.csv for offsite assets requiring whitelisting.
- Use data/posts.json and data/media.json as canonical payloads for database migration.
======================================================================
"""
        with open(summary_txt_path, "w", encoding="utf-8") as f:
            f.write(summary_content)

        self.logger.success(f"Generated audit reports and summary in {reports_dir}")
        return {
            "missing_media_csv": str(missing_csv_path.as_posix()),
            "external_media_csv": str(external_csv_path.as_posix()),
            "download_errors_csv": str(errors_csv_path.as_posix()),
            "summary_txt": str(summary_txt_path.as_posix()),
        }


# Register tool
registry.register(GenerateReportsTool)
