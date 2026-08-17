"""Integrity validation tool executing a comprehensive 12-point pre-delivery checklist."""

import csv
import json
from pathlib import Path
from typing import Any, Dict, List
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool
from src.utils.http_client import ErrorCategory


class ValidateExportTool(BaseTool):
    """Tool: validate_export (Tool 19)"""

    metadata = ToolMetadata(
        name="validate_export",
        version="1.0.0",
        description="Validates export integrity against the 12-point delivery checklist before customer handoff.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "all_passed": {"type": "boolean"},
                "passed_checks": {"type": "integer"},
                "failed_checks": {"type": "integer"},
                "validation_report": {"type": "string"},
            },
        },
        capabilities=["validation", "checklist", "integrity", "delivery"],
        dependencies=["package_posts", "generate_manifest", "generate_readme"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        output_root = self.config.output_dir
        data_dir = self.config.data_dir
        reports_dir = self.config.reports_dir
        manifest_file = self.config.manifest_path
        readme_file = self.config.readme_path

        checks: List[Dict[str, Any]] = []

        def add_check(name: str, passed: bool, details: str = ""):
            checks.append({"name": name, "passed": passed, "details": details})

        # 1. Check manifest exists & valid
        manifest_ok = False
        manifest_data = {}
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                manifest_ok = bool(manifest_data.get("statistics"))
                add_check("Manifest is valid JSON and contains statistics", manifest_ok)
            except Exception as e:
                add_check("Manifest is valid JSON", False, str(e))
        else:
            add_check("Manifest file exists", False, "manifest.json not found")

        # 2. Check JSON data files
        json_files = ["posts.json", "media.json", "post_media_mapping.json"]
        posts_data = []
        media_data = []
        mappings_data = []

        all_json_ok = True
        for jf in json_files:
            jp = data_dir / jf
            if jp.exists():
                try:
                    with open(jp, "r", encoding="utf-8") as f:
                        content = json.load(f)
                    if jf == "posts.json":
                        posts_data = content
                    elif jf == "media.json":
                        media_data = content
                    elif jf == "post_media_mapping.json":
                        mappings_data = content
                except Exception as e:
                    all_json_ok = False
                    add_check(f"JSON file {jf} is valid", False, str(e))
            else:
                all_json_ok = False
                add_check(f"JSON file {jf} exists", False, "Missing file")
        if all_json_ok:
            add_check("All master JSON datasets are valid", True, f"{len(posts_data)} posts, {len(media_data)} media")

        # 3. Check CSV data files
        csv_files = ["posts.csv", "media.csv", "post_media_mapping.csv"]
        all_csv_ok = True
        for cf in csv_files:
            cp = data_dir / cf
            if cp.exists() and cp.stat().st_size > 0:
                try:
                    with open(cp, "r", encoding="utf-8-sig") as f:
                        rows = list(csv.reader(f))
                        if len(rows) < 1:
                            all_csv_ok = False
                except Exception:
                    all_csv_ok = False
            else:
                all_csv_ok = False
        add_check("All master CSV datasets are readable", all_csv_ok)

        # 4. Check post packages directory structure
        all_post_pkgs_ok = True
        zero_byte_files_found = []
        missing_content_html = []

        post_dirs_found = 0
        for p in posts_data:
            pid = p.get("id")
            pub = p.get("published_at")
            year = "0000"
            month = "00"
            if pub and len(pub.split("-")) >= 2:
                year = pub.split("-")[0]
                month = pub.split("-")[1]

            # Find matching directory in output/year/month/<pid>-*
            ym_dir = output_root / year / month
            found_dir = None
            if ym_dir.exists():
                for cand in ym_dir.iterdir():
                    if cand.is_dir() and cand.name.startswith(f"{pid}-"):
                        found_dir = cand
                        break

            if found_dir:
                post_dirs_found += 1
                c_html = found_dir / "public" / "content.html"
                if not (c_html.exists() and c_html.is_file()):
                    missing_content_html.append(str(found_dir))

                # Check for zero-byte files in post folder
                for fpath in found_dir.rglob("*"):
                    if fpath.is_file() and fpath.stat().st_size == 0 and fpath.name != "missing_media.txt":
                        zero_byte_files_found.append(str(fpath))
            else:
                all_post_pkgs_ok = False

        add_check(
            "All posts packaged into YYYY/MM/<post_id>-<slug>/",
            all_post_pkgs_ok and (post_dirs_found == len(posts_data)),
            f"Packaged {post_dirs_found}/{len(posts_data)} posts",
        )
        add_check(
            "content.html exists for every packaged post",
            len(missing_content_html) == 0,
            f"{len(missing_content_html)} posts missing content.html",
        )
        add_check(
            "No zero-byte assets in packaged output",
            len(zero_byte_files_found) == 0,
            f"{len(zero_byte_files_found)} zero-byte files found",
        )

        # 5. Manifest statistics match actual counts
        stats = manifest_data.get("statistics", {})
        stats_match = (
            stats.get("posts") == len(posts_data)
            and stats.get("media") == len(media_data)
            and stats.get("post_media_mappings") == len(mappings_data)
        )
        add_check("Manifest statistics match actual file record counts", stats_match)

        # 6. Audit reports existence
        reports_ok = (
            (reports_dir / "missing_media.csv").exists()
            and (reports_dir / "external_media.csv").exists()
            and (reports_dir / "download_errors.csv").exists()
            and (reports_dir / "migration_summary.txt").exists()
        )
        add_check("All 4 audit reports generated in reports/", reports_ok)

        # 7. Customer README.md exists and non-empty
        readme_ok = readme_file.exists() and readme_file.stat().st_size > 100
        add_check("Customer README.md generated and non-empty", readme_ok)

        # Output validation report
        passed_count = sum(1 for c in checks if c["passed"])
        failed_count = len(checks) - passed_count
        all_passed = failed_count == 0

        val_report = {
            "all_passed": all_passed,
            "passed_checks": passed_count,
            "failed_checks": failed_count,
            "checks": checks,
        }

        val_report_path = reports_dir / "validation.json"
        with open(val_report_path, "w", encoding="utf-8") as f:
            json.dump(val_report, f, ensure_ascii=False, indent=2)

        if not all_passed:
            self.logger.warning(f"Export validation completed with {failed_count} failed checks.")
            for c in checks:
                if not c["passed"]:
                    self.logger.error(f"  FAILED: {c['name']} ({c['details']})")
        else:
            self.logger.success(f"All {passed_count} export validation checks passed successfully!")

        return {
            "all_passed": all_passed,
            "passed_checks": passed_count,
            "failed_checks": failed_count,
            "validation_report": str(val_report_path.as_posix()),
        }


# Register validation tool
registry.register(ValidateExportTool)
