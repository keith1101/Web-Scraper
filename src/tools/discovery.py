"""Discovery tool for inspecting WordPress REST API endpoints and routes."""

import json
from pathlib import Path
from typing import Any, Dict
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool
from src.utils.http_client import ErrorCategory


class DiscoverWordpressApiTool(BaseTool):
    """Tool: discover_wordpress_api (Tool 01)"""

    metadata = ToolMetadata(
        name="discover_wordpress_api",
        version="1.0.0",
        description="Inspects /wp-json/ to discover registered routes, authentication, and endpoint capabilities.",
        input_schema={
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
            },
            "required": ["base_url"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "routes_path": {"type": "string"},
                "has_posts": {"type": "boolean"},
                "has_media": {"type": "boolean"},
                "has_categories": {"type": "boolean"},
                "has_tags": {"type": "boolean"},
                "endpoints_count": {"type": "integer"},
            },
        },
        capabilities=["wordpress", "rest-api", "discovery", "routes"],
        dependencies=[],
        status=ToolStatus.READY,
    )

    def _execute(self, base_url: str, **kwargs) -> Dict[str, Any]:
        target_url = f"{base_url.rstrip('/')}/wp-json/"
        self.logger.info(f"Discovering WordPress REST API at {target_url}...")

        auth = None
        if self.config.wp_username and self.config.wp_app_password:
            auth = (self.config.wp_username, self.config.wp_app_password)

        res = self.http_client.get_json(target_url, auth=auth)
        if not res.success:
            err = RuntimeError(f"Failed to connect to /wp-json/: {res.error_message}")
            setattr(err, "error_type", res.error_type or ErrorCategory.NETWORK_ERROR)
            raise err

        routes_data = res.data or {}
        routes = routes_data.get("routes", {})
        endpoints_count = len(routes)

        has_posts = "/wp/v2/posts" in routes
        has_media = "/wp/v2/media" in routes
        has_categories = "/wp/v2/categories" in routes
        has_tags = "/wp/v2/tags" in routes

        out_path = self.config.discovery_dir / "routes.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(routes_data, f, ensure_ascii=False, indent=2)

        self.logger.info(
            f"Discovered {endpoints_count} routes (posts={has_posts}, media={has_media}, "
            f"categories={has_categories}, tags={has_tags})"
        )

        return {
            "routes_path": str(out_path.as_posix()),
            "has_posts": has_posts,
            "has_media": has_media,
            "has_categories": has_categories,
            "has_tags": has_tags,
            "endpoints_count": endpoints_count,
        }


# Register tool
registry.register(DiscoverWordpressApiTool)
