"""Media downloader tool with idempotency, error classification, and structure preservation."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool
from src.utils.http_client import ErrorCategory


class DownloadMediaTool(BaseTool):
    """Tool: download_media (Tool 06)"""

    metadata = ToolMetadata(
        name="download_media",
        version="1.0.0",
        description="Downloads original media files preserving YYYY/MM structure with idempotency and verification.",
        input_schema={
            "type": "object",
            "properties": {
                "media_file": {"type": "string"},
                "max_items": {"type": "integer", "default": 0},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "total_items": {"type": "integer"},
                "downloaded": {"type": "integer"},
                "already_exists": {"type": "integer"},
                "failed": {"type": "integer"},
                "manifest_file": {"type": "string"},
            },
        },
        capabilities=["wordpress", "media", "downloader", "idempotent"],
        dependencies=["scrape_public_media"],
        status=ToolStatus.READY,
    )

    def _execute(
        self,
        media_file: Optional[str] = None,
        max_items: int = 0,
        **kwargs,
    ) -> Dict[str, Any]:
        media_path = Path(media_file) if media_file else (self.config.raw_dir / "media_public.json")
        if not media_path.exists():
            err = FileNotFoundError(f"Media metadata file not found at {media_path}")
            setattr(err, "error_type", ErrorCategory.FILESYSTEM_ERROR)
            raise err

        with open(media_path, "r", encoding="utf-8") as f:
            media_items = json.load(f)

        if not isinstance(media_items, list):
            err = ValueError(f"Expected list of media records, got {type(media_items)}")
            setattr(err, "error_type", ErrorCategory.SCHEMA_ERROR)
            raise err

        if max_items > 0:
            media_items = media_items[:max_items]

        dest_root = self.config.workspace_media_dir
        dest_root.mkdir(parents=True, exist_ok=True)

        downloaded_count = 0
        exists_count = 0
        failed_count = 0
        records: List[Dict[str, Any]] = []

        self.logger.info(f"Processing media downloads for {len(media_items)} items...")

        for index, item in enumerate(media_items, start=1):
            media_id = item.get("id")
            source_url = item.get("source_url")

            if not source_url:
                continue

            # Determine relative path (WordPress typically provides YYYY/MM/file in media_details.file)
            relative_path = item.get("media_details", {}).get("file")
            if relative_path:
                destination = dest_root / relative_path
            else:
                parsed_path = unquote(urlparse(source_url).path)
                filename = Path(parsed_path).name or f"media_{media_id}.bin"
                destination = dest_root / filename

            destination.parent.mkdir(parents=True, exist_ok=True)

            # Idempotency check: if valid file exists and non-zero
            if destination.exists() and destination.stat().st_size > 0:
                exists_count += 1
                records.append({
                    "media_id": media_id,
                    "source_url": source_url,
                    "local_path": str(destination.relative_to(dest_root).as_posix()),
                    "http_status": 200,
                    "download_status": "EXISTS",
                    "file_size": destination.stat().st_size,
                })
                continue

            # Perform download
            res = self.http_client.download_file(source_url, str(destination))
            if res.success:
                downloaded_count += 1
                file_size = destination.stat().st_size if destination.exists() else 0
                records.append({
                    "media_id": media_id,
                    "source_url": source_url,
                    "local_path": str(destination.relative_to(dest_root).as_posix()),
                    "http_status": 200,
                    "download_status": "DOWNLOADED",
                    "file_size": file_size,
                })
            else:
                failed_count += 1
                status_code = res.status_code
                status_str = "DOWNLOAD_ERROR"
                if status_code == 404:
                    status_str = "HTTP_404"
                elif status_code == 403:
                    status_str = "HTTP_403"
                elif res.error_type == ErrorCategory.SSL_ERROR:
                    status_str = "SSL_ERROR"
                elif res.error_type == ErrorCategory.TIMEOUT:
                    status_str = "TIMEOUT"

                records.append({
                    "media_id": media_id,
                    "source_url": source_url,
                    "local_path": None,
                    "http_status": status_code,
                    "download_status": status_str,
                    "file_size": 0,
                    "error": res.error_message,
                })

            if index % 25 == 0 or index == len(media_items):
                self.logger.info(
                    f"  [{index}/{len(media_items)}] Downloaded: {downloaded_count}, "
                    f"Exists: {exists_count}, Failed: {failed_count}"
                )

        manifest_file = self.config.state_dir / "download_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        self.logger.success(
            f"Media acquisition complete: {downloaded_count} downloaded, "
            f"{exists_count} existing, {failed_count} failures."
        )

        return {
            "total_items": len(media_items),
            "downloaded": downloaded_count,
            "already_exists": exists_count,
            "failed": failed_count,
            "manifest_file": str(manifest_file.as_posix()),
        }


# Register tool
registry.register(DownloadMediaTool)
