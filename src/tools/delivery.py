"""Delivery metadata tools for manifest.json and customer-facing README.md generation."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from src.agent.registry import ToolMetadata, ToolStatus, registry
from src.tools.base import BaseTool


class GenerateManifestTool(BaseTool):
    """Tool: generate_manifest (Tool 17)"""

    metadata = ToolMetadata(
        name="generate_manifest",
        version="1.0.0",
        description="Calculates dynamic export statistics and produces root manifest.json.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "manifest_file": {"type": "string"},
                "total_posts": {"type": "integer"},
                "total_media": {"type": "integer"},
            },
        },
        capabilities=["manifest", "metadata", "delivery"],
        dependencies=["generate_json", "generate_reports"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        posts_path = self.config.data_dir / "posts.json"
        media_path = self.config.data_dir / "media.json"
        mapping_path = self.config.data_dir / "post_media_mapping.json"
        recovery_path = self.config.state_dir / "recovery_report.json"

        with open(posts_path, "r", encoding="utf-8") as f:
            posts = json.load(f)
        with open(media_path, "r", encoding="utf-8") as f:
            media = json.load(f)
        with open(mapping_path, "r", encoding="utf-8") as f:
            mappings = json.load(f)

        unresolved_count = 0
        unknown_refs_count = 0
        external_count = 0
        if recovery_path.exists():
            with open(recovery_path, "r", encoding="utf-8") as f:
                rec_data = json.load(f)
                unresolved_count = len(rec_data.get("unresolved_records", []))
                unknown_refs_count = sum(1 for r in rec_data.get("unresolved_records", []) if r.get("status") == "ORPHAN_MEDIA")
                external_count = len(rec_data.get("external_records", []))

        featured_count = sum(1 for m in mappings if "featured" in m.get("relations", []))
        content_count = sum(1 for m in mappings if "content" in m.get("relations", []))
        attached_count = sum(1 for m in mappings if "attached" in m.get("relations", []))

        # Dynamic tool versions
        tool_versions = {
            meta.name: meta.version
            for meta in registry.list_tools()
        }

        manifest_data = {
            "format_version": "1.0",
            "source": {
                "type": "wordpress",
                "url": self.config.source_url,
            },
            "export": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pipeline_version": "1.0.0",
                "tools": tool_versions,
            },
            "statistics": {
                "posts": len(posts),
                "media": len(media),
                "post_media_mappings": len(mappings),
                "featured_relations": featured_count,
                "content_relations": content_count,
                "attached_relations": attached_count,
                "missing_media": unresolved_count,
                "unknown_media_references": unknown_refs_count,
                "external_media": external_count,
            },
            "directories": {
                "datasets": "data/",
                "reports": "reports/",
                "post_packages": "YYYY/MM/<post_id>-<slug>/",
            },
        }

        out_path = self.config.manifest_path
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)

        self.logger.success(f"Generated dynamic delivery manifest at {out_path}")
        return {
            "manifest_file": str(out_path.as_posix()),
            "total_posts": len(posts),
            "total_media": len(media),
        }


class GenerateReadmeTool(BaseTool):
    """Tool: generate_readme (Tool 18)"""

    metadata = ToolMetadata(
        name="generate_readme",
        version="1.0.0",
        description="Generates customer-facing README.md document with complete migration guidance.",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {"readme_file": {"type": "string"}},
        },
        capabilities=["documentation", "readme", "delivery"],
        dependencies=["generate_manifest"],
        status=ToolStatus.READY,
    )

    def _execute(self, **kwargs) -> Dict[str, Any]:
        manifest_path = self.config.manifest_path
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        stats = manifest.get("statistics", {})
        source_url = manifest.get("source", {}).get("url", "")
        export_date = manifest.get("export", {}).get("created_at", "")

        readme_content = f"""# WordPress Export & Migration Package

## 1. Overview
- **Source Website**: `{source_url}`
- **Export Date**: `{export_date}`
- **Package Format Version**: `1.0`
- **Total Published Posts**: `{stats.get('posts', 0)}`
- **Total Media Assets**: `{stats.get('media', 0)}`
- **Post-Media Mappings**: `{stats.get('post_media_mappings', 0)}`

---

## 2. Directory Structure

```text
root/
├── data/
│   ├── posts.json                 # Canonical master posts JSON
│   ├── posts.csv                  # Tabular posts for Excel review
│   ├── media.json                 # Canonical master media JSON
│   ├── media.csv                  # Tabular media for Excel review
│   ├── post_media_mapping.json    # Canonical relational mappings
│   └── post_media_mapping.csv     # Tabular mappings for Excel review
│
├── reports/
│   ├── missing_media.csv          # Unresolved & missing media references
│   ├── external_media.csv         # Off-site media assets and status
│   ├── download_errors.csv        # Detailed download network/HTTP errors
│   └── migration_summary.txt      # Human-readable export summary
│
├── YYYY/
│   └── MM/
│       └── <post_id>-<slug>/
│           ├── public/
│           │   ├── post.json      # Per-post structured metadata
│           │   ├── content.html   # Canonical HTML content representation
│           │   └── content.md     # Converted Markdown representation
│           │
│           ├── image/             # Downloaded post image assets
│           ├── attachments/       # Non-image files (PDFs, DOCX, ZIPs, etc.)
│           └── missing_media.txt  # Detailed missing assets (only if present)
│
├── manifest.json                  # Machine-readable delivery manifest
└── README.md                      # Customer-facing documentation
```

---

## 3. Dataset Explanations

### `data/posts.json` & `posts.csv`
Contains all published posts exported from WordPress.
- `id`: Stable WordPress Post ID.
- `slug`: URL slug.
- `published_at`: Original publication timestamp (used for directory hierarchy `YYYY/MM`).
- `content_html`: Original rendered WordPress content.
- `category_ids`, `tag_ids`: Taxonomy reference arrays.

### `data/media.json` & `media.csv`
Contains all media attachment metadata.
- `id`: WordPress Media Attachment ID.
- `relative_path`: Preserved `YYYY/MM/filename` upload path.
- `file_exists`: Boolean indicating whether the asset is physically available locally.
- `filesize`, `width`, `height`: Asset dimensional and byte metadata.

### `data/post_media_mapping.json` & `post_media_mapping.csv`
Comprehensive relation graph connecting posts to their media assets:
- `featured`: Featured/thumbnail image assigned to the post.
- `content`: Media embedded in the post's body content (extracted via `wp-image-*` classes and `/wp-content/uploads/` URLs).
- `attached`: Media attachments where `post_parent` equals this post.

---

## 4. Content Representation: HTML vs Markdown
- **Canonical Representation (`content.html`)**: Always represents 100% faithful original WordPress markup.
- **Convenience Representation (`content.md`)**: Automatically converted Markdown for modern Headless CMS platforms (e.g. Strapi, Contentful, Astro, Next.js).

---

## 5. Missing & External Media Handling
- If any post contains broken or deleted media links, a `missing_media.txt` is created inside that post's directory.
- All unresolved media is logged in `reports/missing_media.csv` with the root cause (e.g. `HTTP 404`, `BROKEN_REFERENCE`, `ORPHAN_MEDIA`).
- External images hosted outside the source domain are logged in `reports/external_media.csv`.

---

## 6. Migration Recommendations
1. Use `data/posts.json` and `data/media.json` for database ingestion scripts.
2. Ingest `image/` and `attachments/` folders located in each post folder into your target S3/CDN bucket.
3. Review `reports/missing_media.csv` before decommissioning the legacy WordPress instance.
"""
        out_path = self.config.readme_path
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(readme_content)

        self.logger.success(f"Generated customer delivery README at {out_path}")
        return {"readme_file": str(out_path.as_posix())}


# Register delivery tools
registry.register(GenerateManifestTool)
registry.register(GenerateReadmeTool)
