"""Dataset formatting tools for generating canonical JSON and flattened CSV datasets."""

import csv
import json
import shutil
from pathlib import Path
from typing import Any, Dict
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool


class GenerateJsonTool(BaseTool):
    """Tool: generate_json (Tool 14)"""

    metadata = ToolMetadata(
        name="generate_json",
        version="1.0.0",
        description="Generates master JSON datasets in data/ folder for database migration.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "posts_json": {"type": "string"},
                "media_json": {"type": "string"},
                "mapping_json": {"type": "string"},
            },
        },
        capabilities=["datasets", "json", "delivery"],
        dependencies=["normalize_posts", "normalize_media", "map_post_media"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        data_dir = self.config.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        src_posts = self.config.normalized_dir / "posts.json"
        src_media = self.config.normalized_dir / "media.json"
        src_map = self.config.normalized_dir / "post_media_mapping.json"

        dest_posts = data_dir / "posts.json"
        dest_media = data_dir / "media.json"
        dest_map = data_dir / "post_media_mapping.json"

        shutil.copy2(src_posts, dest_posts)
        shutil.copy2(src_media, dest_media)
        shutil.copy2(src_map, dest_map)

        self.logger.success(f"Generated master JSON datasets in {data_dir}")
        return {
            "posts_json": str(dest_posts.as_posix()),
            "media_json": str(dest_media.as_posix()),
            "mapping_json": str(dest_map.as_posix()),
        }


class GenerateCsvTool(BaseTool):
    """Tool: generate_csv (Tool 15)"""

    metadata = ToolMetadata(
        name="generate_csv",
        version="1.0.0",
        description="Generates flattened CSV versions of posts, media, and mappings for Excel review.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "posts_csv": {"type": "string"},
                "media_csv": {"type": "string"},
                "mapping_csv": {"type": "string"},
            },
        },
        capabilities=["datasets", "csv", "delivery", "flattening"],
        dependencies=["generate_json"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        data_dir = self.config.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        src_posts = self.config.normalized_dir / "posts.json"
        src_media = self.config.normalized_dir / "media.json"
        src_map = self.config.normalized_dir / "post_media_mapping.json"

        dest_posts = data_dir / "posts.csv"
        dest_media = data_dir / "media.csv"
        dest_map = data_dir / "post_media_mapping.csv"

        # 1. Posts CSV
        with open(src_posts, "r", encoding="utf-8") as f:
            posts = json.load(f)

        if posts:
            with open(dest_posts, "w", newline="", encoding="utf-8-sig") as f:
                fieldnames = [
                    "id", "slug", "status", "title", "published_at", "modified_at",
                    "source_url", "author_id", "featured_media_id", "category_ids",
                    "tag_ids", "comment_status"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for p in posts:
                    row = dict(p)
                    if isinstance(row.get("category_ids"), list):
                        row["category_ids"] = ",".join(map(str, row["category_ids"]))
                    if isinstance(row.get("tag_ids"), list):
                        row["tag_ids"] = ",".join(map(str, row["tag_ids"]))
                    writer.writerow(row)

        # 2. Media CSV
        with open(src_media, "r", encoding="utf-8") as f:
            media = json.load(f)

        if media:
            with open(dest_media, "w", newline="", encoding="utf-8-sig") as f:
                fieldnames = [
                    "id", "slug", "filename", "relative_path", "source_url",
                    "media_type", "mime_type", "width", "height", "filesize",
                    "parent_post_id", "uploaded_at", "file_exists", "local_path"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for m in media:
                    writer.writerow(m)

        # 3. Post Media Mapping CSV
        with open(src_map, "r", encoding="utf-8") as f:
            mappings = json.load(f)

        if mappings:
            with open(dest_map, "w", newline="", encoding="utf-8-sig") as f:
                fieldnames = ["post_id", "media_id", "relations", "post_exists", "media_exists", "local_file_exists"]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for item in mappings:
                    row = dict(item)
                    if isinstance(row.get("relations"), list):
                        row["relations"] = ",".join(row["relations"])
                    writer.writerow(row)

        self.logger.success(f"Generated flattened CSV datasets in {data_dir}")
        return {
            "posts_csv": str(dest_posts.as_posix()),
            "media_csv": str(dest_media.as_posix()),
            "mapping_csv": str(dest_map.as_posix()),
        }


# Register formatting tools
registry.register(GenerateJsonTool)
registry.register(GenerateCsvTool)
