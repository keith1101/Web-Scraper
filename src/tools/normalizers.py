"""Normalization tools for transforming raw WordPress outputs into standardized schema and mappings."""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import unquote, urlparse
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool
from src.utils.http_client import ErrorCategory


def _get_rendered(obj: Any, field_name: str) -> str:
    """Safely extract WordPress rendered text/html."""
    if not isinstance(obj, dict):
        return ""
    val = obj.get(field_name, {})
    if isinstance(val, dict):
        return val.get("rendered", "")
    return str(val) if val is not None else ""


def _extract_wp_image_ids(html_content: str) -> List[int]:
    """Extract WordPress media IDs embedded as class 'wp-image-XXXX'."""
    if not html_content:
        return []
    ids = re.findall(r"\bwp-image-(\d+)\b", html_content, flags=re.IGNORECASE)
    return list(dict.fromkeys(int(x) for x in ids))


def _extract_media_urls(html_content: str) -> List[str]:
    """Extract src, href, and srcset URLs from HTML."""
    if not html_content:
        return []
    urls = re.findall(r'''(?:src|href)=["']([^"']+)["']''', html_content, flags=re.IGNORECASE)
    
    # Also parse srcset
    srcset_matches = re.findall(r'''srcset=["']([^"']+)["']''', html_content, flags=re.IGNORECASE)
    for s in srcset_matches:
        for candidate in s.split(","):
            url_part = candidate.strip().split(" ")[0]
            if url_part:
                urls.append(url_part)

    # Filter relevant uploads / media URLs
    filtered = []
    for u in urls:
        if "/wp-content/uploads/" in u or any(u.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".docx", ".zip"]):
            filtered.append(u)
    return list(dict.fromkeys(filtered))


class NormalizePostsTool(BaseTool):
    """Tool: normalize_posts (Tool 07)"""

    metadata = ToolMetadata(
        name="normalize_posts",
        version="1.0.0",
        description="Normalizes raw WordPress posts into the stable internal migration schema.",
        input_schema={
            "type": "object",
            "properties": {"raw_posts_file": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "normalization", "posts"],
        dependencies=["scrape_public_posts"],
        status=ToolStatus.READY,
    )

    def _execute(self, raw_posts_file: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        in_path = Path(raw_posts_file) if raw_posts_file else (self.config.raw_dir / "posts_public.json")
        if not in_path.exists():
            err = FileNotFoundError(f"Raw posts file not found at {in_path}")
            setattr(err, "error_type", ErrorCategory.FILESYSTEM_ERROR)
            raise err

        with open(in_path, "r", encoding="utf-8") as f:
            raw_posts = json.load(f)

        normalized_posts = []
        for post in raw_posts:
            norm = {
                "id": post.get("id"),
                "type": post.get("type", "post"),
                "status": post.get("status", "publish"),
                "slug": post.get("slug", ""),
                "source_url": post.get("link", ""),
                "published_at": post.get("date"),
                "published_at_gmt": post.get("date_gmt"),
                "modified_at": post.get("modified"),
                "modified_at_gmt": post.get("modified_gmt"),
                "title": _get_rendered(post, "title"),
                "content_html": _get_rendered(post, "content"),
                "excerpt_html": _get_rendered(post, "excerpt"),
                "author_id": post.get("author"),
                "featured_media_id": post.get("featured_media") or None,
                "category_ids": post.get("categories") or [],
                "tag_ids": post.get("tags") or [],
                "comment_status": post.get("comment_status", "open"),
            }
            normalized_posts.append(norm)

        out_path = self.config.normalized_dir / "posts.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(normalized_posts, f, ensure_ascii=False, indent=2)

        self.logger.success(f"Normalized {len(normalized_posts)} posts saved to {out_path}")
        return {"output_file": str(out_path.as_posix()), "count": len(normalized_posts)}


class NormalizeMediaTool(BaseTool):
    """Tool: normalize_media (Tool 08)"""

    metadata = ToolMetadata(
        name="normalize_media",
        version="1.0.0",
        description="Normalizes raw WordPress media records and assesses local disk existence.",
        input_schema={
            "type": "object",
            "properties": {"raw_media_file": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "count": {"type": "integer"},
                "existing_local_files": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "normalization", "media"],
        dependencies=["scrape_public_media"],
        status=ToolStatus.READY,
    )

    def _execute(self, raw_media_file: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        in_path = Path(raw_media_file) if raw_media_file else (self.config.raw_dir / "media_public.json")
        if not in_path.exists():
            err = FileNotFoundError(f"Raw media file not found at {in_path}")
            setattr(err, "error_type", ErrorCategory.FILESYSTEM_ERROR)
            raise err

        with open(in_path, "r", encoding="utf-8") as f:
            raw_media = json.load(f)

        media_root = self.config.workspace_media_dir
        normalized_items = []
        existing_local_count = 0

        for item in raw_media:
            details = item.get("media_details") or {}
            relative_path = details.get("file")
            source_url = item.get("source_url", "")

            if not relative_path and source_url:
                parsed = unquote(urlparse(source_url).path)
                relative_path = Path(parsed).name

            local_path = None
            file_exists = False

            if relative_path:
                local_file = media_root / relative_path
                if local_file.is_file() and local_file.stat().st_size > 0:
                    local_path = str(local_file.relative_to(media_root).as_posix())
                    file_exists = True
                    existing_local_count += 1
                else:
                    # Also check flat filename
                    flat_file = media_root / Path(relative_path).name
                    if flat_file.is_file() and flat_file.stat().st_size > 0:
                        local_path = str(flat_file.relative_to(media_root).as_posix())
                        file_exists = True
                        existing_local_count += 1

            filesize = item.get("filesize") or details.get("filesize")

            norm = {
                "id": item.get("id"),
                "type": item.get("type", "attachment"),
                "status": item.get("status", "inherit"),
                "slug": item.get("slug", ""),
                "uploaded_at": item.get("date"),
                "uploaded_at_gmt": item.get("date_gmt"),
                "modified_at": item.get("modified"),
                "title": _get_rendered(item, "title"),
                "caption_html": _get_rendered(item, "caption"),
                "description_html": _get_rendered(item, "description"),
                "alt_text": item.get("alt_text", ""),
                "author_id": item.get("author"),
                "parent_post_id": item.get("post") or None,
                "media_type": item.get("media_type", "image"),
                "mime_type": item.get("mime_type", "image/jpeg"),
                "filename": (
                    item.get("filename")
                    or (Path(relative_path).name if relative_path else None)
                ),
                "relative_path": relative_path,
                "source_url": source_url,
                "width": details.get("width"),
                "height": details.get("height"),
                "filesize": filesize,
                "local_path": local_path,
                "file_exists": file_exists,
            }
            normalized_items.append(norm)

        out_path = self.config.normalized_dir / "media.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(normalized_items, f, ensure_ascii=False, indent=2)

        self.logger.success(
            f"Normalized {len(normalized_items)} media records ({existing_local_count} local files present) "
            f"saved to {out_path}"
        )

        return {
            "output_file": str(out_path.as_posix()),
            "count": len(normalized_items),
            "existing_local_files": existing_local_count,
        }


class ExtractPostMediaTool(BaseTool):
    """Tool: extract_post_media (Tool 09)"""

    metadata = ToolMetadata(
        name="extract_post_media",
        version="1.0.0",
        description="Extracts media references from posts via Strategy A (featured), Strategy B (wp-image-ID), Strategy C (URLs).",
        input_schema={
            "type": "object",
            "properties": {"posts_file": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "posts_processed": {"type": "integer"},
                "total_references": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "extraction", "media-references"],
        dependencies=["normalize_posts"],
        status=ToolStatus.READY,
    )

    def _execute(self, posts_file: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        in_path = Path(posts_file) if posts_file else (self.config.normalized_dir / "posts.json")
        if not in_path.exists():
            err = FileNotFoundError(f"Posts file not found at {in_path}")
            setattr(err, "error_type", ErrorCategory.FILESYSTEM_ERROR)
            raise err

        with open(in_path, "r", encoding="utf-8") as f:
            posts = json.load(f)

        extracted_refs = []
        total_refs_count = 0

        for post in posts:
            post_id = post.get("id")
            featured_media_id = post.get("featured_media_id")
            content_html = post.get("content_html", "")

            # Strategy B: wp-image-ID
            wp_image_ids = _extract_wp_image_ids(content_html)

            # Strategy C: content URLs
            content_urls = _extract_media_urls(content_html)

            item = {
                "post_id": post_id,
                "featured_media_id": featured_media_id,
                "content_media_ids": wp_image_ids,
                "content_media_urls": content_urls,
            }
            extracted_refs.append(item)
            total_refs_count += (1 if featured_media_id else 0) + len(wp_image_ids) + len(content_urls)

        out_path = self.config.normalized_dir / "content_media_refs.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(extracted_refs, f, ensure_ascii=False, indent=2)

        self.logger.info(f"Extracted {total_refs_count} media references across {len(posts)} posts -> {out_path}")
        return {
            "output_file": str(out_path.as_posix()),
            "posts_processed": len(posts),
            "total_references": total_refs_count,
        }


def _normalize_media_key(path_str: str) -> str:
    """Normalize URL or relative path by removing thumbnail dimensions (-WxH) and WordPress (-scaled) suffixes."""
    clean = unquote(urlparse(path_str).path if "://" in path_str else path_str).lower()
    clean = re.sub(r"-\d+x\d+(?=\.[^.]+$)", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"-scaled(?=\.[^.]+$)", "", clean, flags=re.IGNORECASE)
    return clean


class MapPostMediaTool(BaseTool):
    """Tool: map_post_media (Tool 10)"""

    metadata = ToolMetadata(
        name="map_post_media",
        version="1.0.0",
        description="Builds unified Post <-> Media relation mapping from featured, content, and attached sources.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "total_mappings": {"type": "integer"},
                "featured_count": {"type": "integer"},
                "content_count": {"type": "integer"},
                "attached_count": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "mapping", "relations"],
        dependencies=["normalize_posts", "normalize_media", "extract_post_media"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        posts_path = self.config.normalized_dir / "posts.json"
        media_path = self.config.normalized_dir / "media.json"
        refs_path = self.config.normalized_dir / "content_media_refs.json"

        with open(posts_path, "r", encoding="utf-8") as f:
            posts = json.load(f)
        with open(media_path, "r", encoding="utf-8") as f:
            media = json.load(f)

        refs = []
        if refs_path.exists():
            with open(refs_path, "r", encoding="utf-8") as f:
                refs = json.load(f)

        media_by_id = {item["id"]: item for item in media if item.get("id") is not None}
        media_by_url = {item["source_url"]: item for item in media if item.get("source_url")}
        
        # Build normalized path and filename index to match thumbnail variations (e.g. image-300x200.jpg, image-scaled.jpg -> image.jpg)
        media_by_norm_path = {}
        media_by_norm_filename = {}
        for item in media:
            s_url = item.get("source_url")
            if s_url:
                norm_path = _normalize_media_key(s_url)
                media_by_norm_path[norm_path] = item
                norm_filename = Path(norm_path).name
                media_by_norm_filename[norm_filename] = item

        post_ids = {p["id"] for p in posts if p.get("id") is not None}
        relations = defaultdict(set)
        unmapped_urls_by_post = defaultdict(list)

        # 1. Relations from Post / Content Refs
        for ref_item in refs:
            post_id = ref_item.get("post_id")
            if not post_id:
                continue

            # Featured
            feat_id = ref_item.get("featured_media_id")
            if feat_id:
                relations[(post_id, int(feat_id))].add("featured")

            # Content wp-image-{id}
            for mid in ref_item.get("content_media_ids", []):
                relations[(post_id, int(mid))].add("content")

            # Content URLs
            for url in ref_item.get("content_media_urls", []):
                matched_item = media_by_url.get(url)
                if not matched_item:
                    norm_path = _normalize_media_key(url)
                    matched_item = media_by_norm_path.get(norm_path)

                if not matched_item:
                    norm_filename = Path(_normalize_media_key(url)).name
                    matched_item = media_by_norm_filename.get(norm_filename)

                if matched_item and matched_item.get("id"):
                    relations[(post_id, matched_item["id"])].add("content")
                else:
                    unmapped_urls_by_post[post_id].append(url)

        # 2. Relations from Media (Parent Post attachments)
        for item in media:
            mid = item.get("id")
            parent_id = item.get("parent_post_id")
            if mid and parent_id:
                relations[(int(parent_id), int(mid))].add("attached")

        # Build final mapping output
        mapping_records = []
        featured_count = 0
        content_count = 0
        attached_count = 0

        for (p_id, m_id), rel_types in sorted(relations.items()):
            rel_list = sorted(list(rel_types))
            if "featured" in rel_list:
                featured_count += 1
            if "content" in rel_list:
                content_count += 1
            if "attached" in rel_list:
                attached_count += 1

            m_obj = media_by_id.get(m_id)
            mapping_records.append({
                "post_id": p_id,
                "media_id": m_id,
                "relations": rel_list,
                "post_exists": p_id in post_ids,
                "media_exists": m_id in media_by_id,
                "local_file_exists": bool(m_obj and m_obj.get("file_exists")),
            })

        out_path = self.config.normalized_dir / "post_media_mapping.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(mapping_records, f, ensure_ascii=False, indent=2)

        # Save unmapped URLs for recovery tool
        unmapped_file = self.config.state_dir / "unmapped_content_urls.json"
        with open(unmapped_file, "w", encoding="utf-8") as f:
            json.dump(dict(unmapped_urls_by_post), f, ensure_ascii=False, indent=2)

        self.logger.success(
            f"Mapping complete: {len(mapping_records)} mappings (featured: {featured_count}, "
            f"content: {content_count}, attached: {attached_count}) -> {out_path}"
        )

        return {
            "output_file": str(out_path.as_posix()),
            "total_mappings": len(mapping_records),
            "featured_count": featured_count,
            "content_count": content_count,
            "attached_count": attached_count,
        }


# Register normalizer tools
registry.register(NormalizePostsTool)
registry.register(NormalizeMediaTool)
registry.register(ExtractPostMediaTool)
registry.register(MapPostMediaTool)
