"""Recovery tools for detecting missing media, retrying downloads, and error classification."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool
from src.utils.http_client import ErrorCategory


class ValidateMediaTool(BaseTool):
    """Tool: validate_media (Tool 11)"""

    metadata = ToolMetadata(
        name="validate_media",
        version="1.0.0",
        description="Scans all normalized media to verify disk presence, non-zero file sizes, and valid paths.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "total_media": {"type": "integer"},
                "valid_files": {"type": "integer"},
                "missing_files": {"type": "integer"},
                "zero_byte_files": {"type": "integer"},
            },
        },
        capabilities=["media", "validation", "integrity"],
        dependencies=["normalize_media"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        media_path = self.config.normalized_dir / "media.json"
        with open(media_path, "r", encoding="utf-8") as f:
            media = json.load(f)

        media_root = self.config.workspace_media_dir
        valid_count = 0
        missing_count = 0
        zero_byte_count = 0
        health_records = []

        for item in media:
            rel_path = item.get("relative_path")
            source_url = item.get("source_url")
            local_file = None

            if rel_path:
                cand = media_root / rel_path
                if cand.exists():
                    local_file = cand
                else:
                    flat_cand = media_root / Path(rel_path).name
                    if flat_cand.exists():
                        local_file = flat_cand

            is_valid = False
            size = 0
            status = "MISSING"

            if local_file and local_file.is_file():
                size = local_file.stat().st_size
                if size > 0:
                    is_valid = True
                    status = "VALID"
                    valid_count += 1
                else:
                    status = "ZERO_BYTE"
                    zero_byte_count += 1
            else:
                missing_count += 1

            health_records.append({
                "id": item.get("id"),
                "source_url": source_url,
                "relative_path": rel_path,
                "status": status,
                "file_size": size,
            })

        out_path = self.config.state_dir / "media_health.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(health_records, f, ensure_ascii=False, indent=2)

        self.logger.info(
            f"Media validation: {valid_count} valid, {missing_count} missing, "
            f"{zero_byte_count} zero-byte files."
        )

        return {
            "total_media": len(media),
            "valid_files": valid_count,
            "missing_files": missing_count,
            "zero_byte_files": zero_byte_count,
        }


class RecoverMissingMediaTool(BaseTool):
    """Tool: recover_missing_media (Tool 12)"""

    metadata = ToolMetadata(
        name="recover_missing_media",
        version="1.0.0",
        description="Retries failed media downloads, unmapped URLs, and categorizes unrecoverable references.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "recovered_count": {"type": "integer"},
                "unresolved_count": {"type": "integer"},
                "external_count": {"type": "integer"},
            },
        },
        capabilities=["media", "recovery", "retry-backoff", "error-classification"],
        dependencies=["validate_media", "map_post_media"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        media_path = self.config.normalized_dir / "media.json"
        mapping_path = self.config.normalized_dir / "post_media_mapping.json"
        unmapped_path = self.config.state_dir / "unmapped_content_urls.json"

        with open(media_path, "r", encoding="utf-8") as f:
            media = json.load(f)
        with open(mapping_path, "r", encoding="utf-8") as f:
            mappings = json.load(f)

        unmapped_urls_by_post = {}
        if unmapped_path.exists():
            with open(unmapped_path, "r", encoding="utf-8") as f:
                unmapped_urls_by_post = json.load(f)

        media_by_id = {item["id"]: item for item in media if item.get("id") is not None}
        media_root = self.config.workspace_media_dir

        recovered_count = 0
        unresolved_records = []
        external_records = []
        download_errors = []

        # 1. Check media items with missing local files
        for item in media:
            mid = item.get("id")
            source_url = item.get("source_url")
            rel_path = item.get("relative_path")

            if item.get("file_exists"):
                continue

            # Check both relative path and flat filename
            local_exists = False
            if rel_path:
                cand = media_root / rel_path
                flat_cand = media_root / Path(rel_path).name
                if (cand.is_file() and cand.stat().st_size > 0) or (flat_cand.is_file() and flat_cand.stat().st_size > 0):
                    local_exists = True
                    item["file_exists"] = True

            if local_exists:
                continue

            if not rel_path and source_url:
                rel_path = Path(unquote(urlparse(source_url).path)).name

            dest = media_root / (rel_path or f"media_{mid}.bin")

            if source_url:
                self.logger.info(f"Attempting recovery download for media ID {mid}: {source_url}")
                res = self.http_client.download_file(source_url, str(dest))
                if res.success:
                    recovered_count += 1
                    item["file_exists"] = True
                    item["local_path"] = str(dest.relative_to(media_root).as_posix())
                else:
                    reason = res.error_message or "Download Failed"
                    status = "DOWNLOAD_ERROR"
                    if res.status_code == 404:
                        status = "BROKEN_REFERENCE"
                        reason = "HTTP 404 Not Found"
                    elif res.status_code == 403:
                        status = "RESTRICTED"
                        reason = "HTTP 403 Forbidden"
                    elif res.error_type == ErrorCategory.SSL_ERROR:
                        status = "SSL_ERROR"

                    download_errors.append({
                        "media_id": mid,
                        "source_url": source_url,
                        "status": status,
                        "reason": reason,
                    })

        # 2. Check unmapped URLs in post content concurrently
        base_url = self.config.source_url
        url_download_cache: Dict[str, Any] = {}

        # Collect all unique unmapped URLs
        unique_urls = set()
        for urls in unmapped_urls_by_post.values():
            for u in urls:
                unique_urls.add(u)

        def _fetch_url(url: str) -> Tuple[str, Dict[str, Any]]:
            import hashlib
            is_ext = self.http_client.is_external_url(url, base_url)
            url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
            base_name = Path(unquote(urlparse(url).path)).name or "asset.bin"
            clean_name = re.sub(r"[^\w\-.]", "_", base_name)
            filename = f"{url_hash}_{clean_name}"
            dest = media_root / "recovered" / filename

            # Connect timeout 2s, read timeout 3s, 1 attempt
            res = self.http_client.download_file(url, str(dest), timeout=(2, 3), max_retries=1)
            status_str = "DOWNLOADED" if res.success else "FAILED"
            loc_file = str(dest.relative_to(media_root).as_posix()) if res.success else None
            reason_str = "" if res.success else (res.error_message or "Download unreachable")

            return url, {
                "is_ext": is_ext,
                "status": status_str,
                "local_file": loc_file,
                "reason": reason_str,
                "success": res.success,
            }

        if unique_urls:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as executor:
                for url, res_dict in executor.map(_fetch_url, list(unique_urls)):
                    url_download_cache[url] = res_dict

        # Process results across posts
        for post_id_str, urls in unmapped_urls_by_post.items():
            post_id = int(post_id_str)
            for url in urls:
                res_dict = url_download_cache.get(url, {"is_ext": True, "status": "FAILED", "local_file": None, "reason": "Not checked", "success": False})
                is_ext = res_dict["is_ext"]
                status_str = res_dict["status"]
                loc_file = res_dict["local_file"]
                reason_str = res_dict["reason"]

                if is_ext:
                    external_records.append({
                        "post_id": post_id,
                        "url": url,
                        "domain": urlparse(url).netloc,
                        "download_status": status_str,
                        "local_file": loc_file,
                        "reason": reason_str,
                    })

                if res_dict["success"]:
                    recovered_count += 1
                else:
                    unresolved_records.append({
                        "post_id": post_id,
                        "media_id": None,
                        "relation": "content",
                        "source_url": url,
                        "status": "EXTERNAL_MEDIA" if is_ext else "BROKEN_REFERENCE",
                        "reason": reason_str,
                    })

        # 3. Check mapping references where media was not found in REST API
        for m in mappings:
            if not m.get("media_exists"):
                unresolved_records.append({
                    "post_id": m.get("post_id"),
                    "media_id": m.get("media_id"),
                    "relation": ",".join(m.get("relations", [])),
                    "source_url": "",
                    "status": "ORPHAN_MEDIA",
                    "reason": f"Media ID {m.get('media_id')} not present in WordPress media database",
                })

        # Save recovery state
        rec_report = {
            "recovered_count": recovered_count,
            "unresolved_records": unresolved_records,
            "external_records": external_records,
            "download_errors": download_errors,
        }
        out_path = self.config.state_dir / "recovery_report.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rec_report, f, ensure_ascii=False, indent=2)

        # Update media.json with any recovered file statuses
        with open(media_path, "w", encoding="utf-8") as f:
            json.dump(media, f, ensure_ascii=False, indent=2)

        self.logger.success(
            f"Recovery finished: {recovered_count} files recovered, "
            f"{len(unresolved_records)} unresolved, {len(external_records)} external media items."
        )

        return {
            "recovered_count": recovered_count,
            "unresolved_count": len(unresolved_records),
            "external_count": len(external_records),
        }


# Register recovery tools
registry.register(ValidateMediaTool)
registry.register(RecoverMissingMediaTool)
