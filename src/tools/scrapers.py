"""Scraper tools for fetching posts, media metadata, categories, and tags."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool
from src.utils.http_client import ErrorCategory


class ScrapePublicPostsTool(BaseTool):
    """Tool: scrape_public_posts (Tool 02)"""

    metadata = ToolMetadata(
        name="scrape_public_posts",
        version="1.0.0",
        description="Scrapes all published WordPress posts via REST API pagination.",
        input_schema={
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
                "per_page": {"type": "integer", "default": 100},
                "force_refresh": {"type": "boolean", "default": False},
            },
            "required": ["base_url"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "count": {"type": "integer"},
                "total_expected": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "rest-api", "posts", "pagination"],
        dependencies=["discover_wordpress_api"],
        status=ToolStatus.READY,
    )

    def _execute(
        self,
        base_url: str,
        per_page: int = 100,
        force_refresh: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        out_file = self.config.raw_dir / "posts_public.json"

        # Check existing raw file if not force_refresh
        if not force_refresh and out_file.exists() and out_file.stat().st_size > 0:
            with open(out_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, list) and len(existing) > 0:
                    self.logger.info(f"Reusing existing raw posts file: {out_file} ({len(existing)} posts)")
                    return {
                        "output_file": str(out_file.as_posix()),
                        "count": len(existing),
                        "total_expected": len(existing),
                    }

        all_posts: List[Dict[str, Any]] = []
        page = 1
        total_expected = 0
        auth = (self.config.wp_username, self.config.wp_app_password) if self.config.wp_username else None

        while True:
            self.logger.info(f"Fetching posts page {page}...")
            res = self.http_client.get_json(
                f"{base_url.rstrip('/')}/wp-json/wp/v2/posts",
                params={"per_page": per_page, "page": page, "status": "publish"},
                auth=auth,
            )

            if not res.success:
                # If page > 1 and 400 (out of bounds), end pagination
                if res.status_code == 400 and page > 1:
                    break
                err = RuntimeError(f"Failed fetching posts on page {page}: {res.error_message}")
                setattr(err, "error_type", res.error_type or ErrorCategory.NETWORK_ERROR)
                raise err

            posts = res.data
            if not isinstance(posts, list) or len(posts) == 0:
                break

            all_posts.extend(posts)
            total_pages = int(res.headers.get("X-WP-TotalPages", res.headers.get("x-wp-totalpages", 1)))
            total_expected = int(res.headers.get("X-WP-Total", res.headers.get("x-wp-total", len(all_posts))))

            self.logger.info(f"  Retrieved {len(posts)} posts | Page {page}/{total_pages} | Total: {total_expected}")
            if page >= total_pages:
                break
            page += 1

        # Validation rules
        if len(all_posts) == 0:
            err = ValueError("Scraped 0 posts from WordPress endpoint")
            setattr(err, "error_type", ErrorCategory.SCHEMA_ERROR)
            raise err

        for post in all_posts:
            if "id" not in post or not post.get("id"):
                err = ValueError(f"Post record missing valid 'id': {post}")
                setattr(err, "error_type", ErrorCategory.SCHEMA_ERROR)
                raise err

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_posts, f, ensure_ascii=False, indent=2)

        self.logger.success(f"Saved {len(all_posts)} posts to {out_file}")
        return {
            "output_file": str(out_file.as_posix()),
            "count": len(all_posts),
            "total_expected": total_expected,
        }


class ScrapePublicMediaTool(BaseTool):
    """Tool: scrape_public_media (Tool 03)"""

    metadata = ToolMetadata(
        name="scrape_public_media",
        version="1.0.0",
        description="Scrapes all WordPress attachment/media metadata via REST API pagination.",
        input_schema={
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
                "per_page": {"type": "integer", "default": 100},
                "force_refresh": {"type": "boolean", "default": False},
            },
            "required": ["base_url"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "count": {"type": "integer"},
                "total_expected": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "rest-api", "media", "pagination"],
        dependencies=["discover_wordpress_api"],
        status=ToolStatus.READY,
    )

    def _execute(
        self,
        base_url: str,
        per_page: int = 100,
        force_refresh: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        out_file = self.config.raw_dir / "media_public.json"

        if not force_refresh and out_file.exists() and out_file.stat().st_size > 0:
            with open(out_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, list) and len(existing) > 0:
                    self.logger.info(f"Reusing existing raw media file: {out_file} ({len(existing)} records)")
                    return {
                        "output_file": str(out_file.as_posix()),
                        "count": len(existing),
                        "total_expected": len(existing),
                    }

        all_media: List[Dict[str, Any]] = []
        page = 1
        total_expected = 0
        auth = (self.config.wp_username, self.config.wp_app_password) if self.config.wp_username else None

        while True:
            self.logger.info(f"Fetching media page {page}...")
            res = self.http_client.get_json(
                f"{base_url.rstrip('/')}/wp-json/wp/v2/media",
                params={"per_page": per_page, "page": page},
                auth=auth,
            )

            if not res.success:
                if res.status_code == 400 and page > 1:
                    break
                err = RuntimeError(f"Failed fetching media on page {page}: {res.error_message}")
                setattr(err, "error_type", res.error_type or ErrorCategory.NETWORK_ERROR)
                raise err

            items = res.data
            if not isinstance(items, list) or len(items) == 0:
                break

            all_media.extend(items)
            total_pages = int(res.headers.get("X-WP-TotalPages", res.headers.get("x-wp-totalpages", 1)))
            total_expected = int(res.headers.get("X-WP-Total", res.headers.get("x-wp-total", len(all_media))))

            self.logger.info(f"  Retrieved {len(items)} media | Page {page}/{total_pages} | Total: {total_expected}")
            if page >= total_pages:
                break
            page += 1

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_media, f, ensure_ascii=False, indent=2)

        self.logger.success(f"Saved {len(all_media)} media records to {out_file}")
        return {
            "output_file": str(out_file.as_posix()),
            "count": len(all_media),
            "total_expected": total_expected,
        }


class ScrapeCategoriesTool(BaseTool):
    """Tool: scrape_categories (Tool 04)"""

    metadata = ToolMetadata(
        name="scrape_categories",
        version="1.0.0",
        description="Scrapes all WordPress category taxonomies via REST API.",
        input_schema={
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
                "per_page": {"type": "integer", "default": 100},
            },
            "required": ["base_url"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "rest-api", "categories", "taxonomies"],
        dependencies=["discover_wordpress_api"],
        status=ToolStatus.READY,
    )

    def _execute(self, base_url: str, per_page: int = 100, **kwargs) -> Dict[str, Any]:
        out_file = self.config.raw_dir / "categories.json"
        all_cats: List[Dict[str, Any]] = []
        page = 1
        auth = (self.config.wp_username, self.config.wp_app_password) if self.config.wp_username else None

        while True:
            res = self.http_client.get_json(
                f"{base_url.rstrip('/')}/wp-json/wp/v2/categories",
                params={"per_page": per_page, "page": page},
                auth=auth,
            )
            if not res.success:
                if res.status_code == 400 and page > 1:
                    break
                break
            items = res.data
            if not isinstance(items, list) or len(items) == 0:
                break
            all_cats.extend(items)
            total_pages = int(res.headers.get("X-WP-TotalPages", res.headers.get("x-wp-totalpages", 1)))
            if page >= total_pages:
                break
            page += 1

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_cats, f, ensure_ascii=False, indent=2)

        self.logger.info(f"Saved {len(all_cats)} categories to {out_file}")
        return {"output_file": str(out_file.as_posix()), "count": len(all_cats)}


class ScrapeTagsTool(BaseTool):
    """Tool: scrape_tags (Tool 05)"""

    metadata = ToolMetadata(
        name="scrape_tags",
        version="1.0.0",
        description="Scrapes all WordPress tag taxonomies via REST API.",
        input_schema={
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
                "per_page": {"type": "integer", "default": 100},
            },
            "required": ["base_url"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "output_file": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "rest-api", "tags", "taxonomies"],
        dependencies=["discover_wordpress_api"],
        status=ToolStatus.READY,
    )

    def _execute(self, base_url: str, per_page: int = 100, **kwargs) -> Dict[str, Any]:
        out_file = self.config.raw_dir / "tags.json"
        all_tags: List[Dict[str, Any]] = []
        page = 1
        auth = (self.config.wp_username, self.config.wp_app_password) if self.config.wp_username else None

        while True:
            res = self.http_client.get_json(
                f"{base_url.rstrip('/')}/wp-json/wp/v2/tags",
                params={"per_page": per_page, "page": page},
                auth=auth,
            )
            if not res.success:
                if res.status_code == 400 and page > 1:
                    break
                break
            items = res.data
            if not isinstance(items, list) or len(items) == 0:
                break
            all_tags.extend(items)
            total_pages = int(res.headers.get("X-WP-TotalPages", res.headers.get("x-wp-totalpages", 1)))
            if page >= total_pages:
                break
            page += 1

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_tags, f, ensure_ascii=False, indent=2)

        self.logger.info(f"Saved {len(all_tags)} tags to {out_file}")
        return {"output_file": str(out_file.as_posix()), "count": len(all_tags)}


# Register all scrapers
registry.register(ScrapePublicPostsTool)
registry.register(ScrapePublicMediaTool)
registry.register(ScrapeCategoriesTool)
registry.register(ScrapeTagsTool)
