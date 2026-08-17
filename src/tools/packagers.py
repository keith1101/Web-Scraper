"""Packaging tool for generating customer delivery structure per post."""

import json
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool
from src.utils.html_to_md import HtmlToMarkdownConverter
from src.utils.http_client import ErrorCategory


def _sanitize_slug(slug: Optional[str], post_id: int, title: Optional[str] = None) -> str:
    """Create safe directory slug."""
    if slug and slug.strip():
        clean = re.sub(r"[^\w\-]", "-", slug.strip().lower())
        clean = re.sub(r"-+", "-", clean).strip("-")
        if clean:
            return clean
    if title and title.strip():
        clean = re.sub(r"[^\w\-]", "-", title.strip().lower())
        clean = re.sub(r"-+", "-", clean).strip("-")
        if clean:
            return clean[:60]
    return f"post-{post_id}"


class PackagePostsTool(BaseTool):
    """Tool: package_posts (Tool 13)"""

    metadata = ToolMetadata(
        name="package_posts",
        version="1.0.0",
        description="Packages posts into YYYY/MM/<post_id>-<slug>/ delivery structure with public, image, and attachment assets.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "packaged_posts": {"type": "integer"},
                "images_copied": {"type": "integer"},
                "attachments_copied": {"type": "integer"},
                "posts_with_missing_media": {"type": "integer"},
            },
        },
        capabilities=["packaging", "delivery", "posts", "filesystem"],
        dependencies=["normalize_posts", "map_post_media", "recover_missing_media"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        posts_path = self.config.normalized_dir / "posts.json"
        media_path = self.config.normalized_dir / "media.json"
        mapping_path = self.config.normalized_dir / "post_media_mapping.json"
        recovery_path = self.config.state_dir / "recovery_report.json"

        with open(posts_path, "r", encoding="utf-8") as f:
            posts = json.load(f)
        with open(media_path, "r", encoding="utf-8") as f:
            media = json.load(f)
        with open(mapping_path, "r", encoding="utf-8") as f:
            mappings = json.load(f)

        unresolved_by_post = defaultdict(list)
        if recovery_path.exists():
            with open(recovery_path, "r", encoding="utf-8") as f:
                rec_data = json.load(f)
                for item in rec_data.get("unresolved_records", []):
                    pid = item.get("post_id")
                    if pid:
                        unresolved_by_post[int(pid)].append(item)

        media_by_id = {item["id"]: item for item in media if item.get("id") is not None}
        media_root = self.config.workspace_media_dir

        # Group mappings by post_id
        mappings_by_post = defaultdict(list)
        for m in mappings:
            pid = m.get("post_id")
            if pid:
                mappings_by_post[int(pid)].append(m)

        output_root = self.config.output_dir
        packaged_count = 0
        images_copied = 0
        attachments_copied = 0
        posts_with_missing_count = 0

        self.logger.info(f"Packaging {len(posts)} posts into delivery structure...")

        for post in posts:
            post_id = post["id"]
            title = post.get("title", "")
            slug = _sanitize_slug(post.get("slug"), post_id, title)
            published_at = post.get("published_at")

            # Parse YYYY/MM from published_at
            year = "0000"
            month = "00"
            if published_at:
                try:
                    # ISO 8601 parsing e.g. 2026-08-16T11:00:00
                    dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    year = f"{dt.year:04d}"
                    month = f"{dt.month:02d}"
                except Exception:
                    # Fallback string slicing
                    parts = published_at.split("-")
                    if len(parts) >= 2:
                        year = parts[0]
                        month = parts[1]

            post_dir_name = f"{post_id}-{slug}"
            post_dir = output_root / year / month / post_dir_name
            public_dir = post_dir / "public"
            image_dir = post_dir / "image"
            attachments_dir = post_dir / "attachments"

            public_dir.mkdir(parents=True, exist_ok=True)
            image_dir.mkdir(parents=True, exist_ok=True)
            attachments_dir.mkdir(parents=True, exist_ok=True)

            # 1. Generate public/ files
            # post.json
            with open(public_dir / "post.json", "w", encoding="utf-8") as f:
                json.dump(post, f, ensure_ascii=False, indent=2)

            # content.html (canonical)
            content_html = post.get("content_html", "")
            with open(public_dir / "content.html", "w", encoding="utf-8") as f:
                f.write(content_html or "")

            # content.md (converted)
            content_md, _ = HtmlToMarkdownConverter.convert(content_html)
            with open(public_dir / "content.md", "w", encoding="utf-8") as f:
                f.write(content_md or "")

            # 2. Copy mapped media assets
            post_maps = mappings_by_post.get(post_id, [])
            for map_item in post_maps:
                mid = map_item.get("media_id")
                m_obj = media_by_id.get(mid)
                if not m_obj:
                    continue

                rel_path = m_obj.get("relative_path")
                if not rel_path and m_obj.get("source_url"):
                    rel_path = Path(m_obj["source_url"]).name

                if not rel_path:
                    continue

                src_file = media_root / rel_path
                if not src_file.exists():
                    flat_src = media_root / Path(rel_path).name
                    if flat_src.exists():
                        src_file = flat_src

                if src_file.is_file() and src_file.stat().st_size > 0:
                    media_type = m_obj.get("media_type", "").lower()
                    mime_type = m_obj.get("mime_type", "").lower()
                    file_ext = src_file.suffix.lower()

                    is_img = (
                        media_type == "image"
                        or mime_type.startswith("image/")
                        or file_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif", ".ico"}
                    )

                    dest_folder = image_dir if is_img else attachments_dir
                    target_file = dest_folder / src_file.name
                    if not target_file.exists():
                        shutil.copy2(src_file, target_file)

                    if is_img:
                        images_copied += 1
                    else:
                        attachments_copied += 1

            # 3. Create missing_media.txt only if unresolved media exists for this post
            post_unresolved = unresolved_by_post.get(post_id, [])
            missing_txt_path = post_dir / "missing_media.txt"

            if post_unresolved:
                posts_with_missing_count += 1
                lines = [f"Post ID: {post_id}", f"Title: {title}", ""]
                for item in post_unresolved:
                    mid_str = item.get("media_id") or "N/A"
                    lines.append(f"Media ID: {mid_str}")
                    lines.append(f"URL: {item.get('source_url', 'N/A')}")
                    lines.append(f"Relation: {item.get('relation', 'unknown')}")
                    lines.append(f"Status: {item.get('status', 'MISSING')}")
                    lines.append(f"Reason: {item.get('reason', 'N/A')}")
                    lines.append("-" * 40)

                with open(missing_txt_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            else:
                if missing_txt_path.exists():
                    missing_txt_path.unlink()

            packaged_count += 1

        self.logger.success(
            f"Packaged {packaged_count} posts ({images_copied} images, "
            f"{attachments_copied} attachments, {posts_with_missing_count} posts with missing media)."
        )

        return {
            "packaged_posts": packaged_count,
            "images_copied": images_copied,
            "attachments_copied": attachments_copied,
            "posts_with_missing_media": posts_with_missing_count,
        }


# Register tool
registry.register(PackagePostsTool)
