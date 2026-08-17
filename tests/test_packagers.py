"""Tests for packaging posts into delivery folder structure and validating packaging contracts."""

import json
from pathlib import Path
import pytest
from src.config import PipelineConfig
from src.tools.delivery import GenerateManifestTool, GenerateReadmeTool
from src.tools.formatters import GenerateCsvTool, GenerateJsonTool
from src.tools.packagers import PackagePostsTool
from src.tools.reporters import GenerateReportsTool
from src.tools.validators import ValidateExportTool


def test_packaging_and_validation(tmp_path: Path):
    config = PipelineConfig(
        source_url="https://abi.com.vn",
        workspace_dir=tmp_path / "ws",
        output_dir=tmp_path / "out",
    )
    config.ensure_directories()

    # Seed normalized data
    posts = [{
        "id": 5001,
        "type": "post",
        "status": "publish",
        "slug": "sample-event",
        "source_url": "https://abi.com.vn/sample-event",
        "published_at": "2026-08-16T12:00:00",
        "title": "Sample Event Title",
        "content_html": "<p>Hello world paragraph with <strong>bold</strong> text.</p>",
        "excerpt_html": "<p>Hello world excerpt</p>",
        "author_id": 1,
        "featured_media_id": 9001,
        "category_ids": [10],
        "tag_ids": [],
        "comment_status": "open",
    }]

    # Create dummy local media file
    media_file_rel = "2026/08/sample.jpg"
    local_media_path = config.workspace_media_dir / media_file_rel
    local_media_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_media_path, "wb") as f:
        f.write(b"SAMPLE_IMAGE_DATA_BYTES")

    media = [{
        "id": 9001,
        "type": "attachment",
        "status": "inherit",
        "slug": "sample",
        "uploaded_at": "2026-08-16T12:00:00",
        "title": "Sample Image",
        "author_id": 1,
        "parent_post_id": 5001,
        "media_type": "image",
        "mime_type": "image/jpeg",
        "filename": "sample.jpg",
        "relative_path": media_file_rel,
        "source_url": f"https://abi.com.vn/wp-content/uploads/{media_file_rel}",
        "width": 800,
        "height": 600,
        "filesize": len(b"SAMPLE_IMAGE_DATA_BYTES"),
        "local_path": media_file_rel,
        "file_exists": True,
    }]

    mappings = [{
        "post_id": 5001,
        "media_id": 9001,
        "relations": ["featured", "attached"],
        "post_exists": True,
        "media_exists": True,
        "local_file_exists": True,
    }]

    with open(config.normalized_dir / "posts.json", "w", encoding="utf-8") as f:
        json.dump(posts, f)
    with open(config.normalized_dir / "media.json", "w", encoding="utf-8") as f:
        json.dump(media, f)
    with open(config.normalized_dir / "post_media_mapping.json", "w", encoding="utf-8") as f:
        json.dump(mappings, f)

    # 1. Package posts
    pkg_tool = PackagePostsTool(config)
    res_pkg = pkg_tool.run()
    assert res_pkg.success is True
    assert res_pkg.data["packaged_posts"] == 1
    assert res_pkg.data["images_copied"] == 1

    post_pkg_dir = config.output_dir / "2026" / "08" / "5001-sample-event"
    assert post_pkg_dir.exists()
    assert (post_pkg_dir / "public" / "post.json").exists()
    assert (post_pkg_dir / "public" / "content.html").exists()
    assert (post_pkg_dir / "public" / "content.md").exists()
    assert (post_pkg_dir / "image" / "sample.jpg").exists()
    # missing_media.txt should NOT exist since no missing media
    assert not (post_pkg_dir / "missing_media.txt").exists()

    # 2. Generate JSON & CSV
    assert GenerateJsonTool(config).run().success is True
    assert GenerateCsvTool(config).run().success is True

    # 3. Generate Reports, Manifest, Readme
    assert GenerateReportsTool(config).run().success is True
    assert GenerateManifestTool(config).run().success is True
    assert GenerateReadmeTool(config).run().success is True

    # 4. Final Validation
    val_tool = ValidateExportTool(config)
    res_val = val_tool.run()
    assert res_val.success is True
    assert res_val.data["all_passed"] is True
