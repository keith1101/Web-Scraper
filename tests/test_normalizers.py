"""Tests for normalization of posts, media, HTML to Markdown, and relationship mappings."""

import json
from pathlib import Path
import pytest
from src.config import PipelineConfig
from src.tools.normalizers import (
    ExtractPostMediaTool,
    MapPostMediaTool,
    NormalizeMediaTool,
    NormalizePostsTool,
    _extract_media_urls,
    _extract_wp_image_ids,
)
from src.utils.html_to_md import HtmlToMarkdownConverter


def test_html_to_md_conversion():
    sample_html = """
    <h2>Article Heading</h2>
    <p>This is a <strong>bold</strong> and <em>italic</em> sentence with a <a href="https://abi.com.vn">link</a>.</p>
    <blockquote>Wise quote here</blockquote>
    <pre><code>def hello():\n    return 'world'</code></pre>
    <img src="https://abi.com.vn/wp-content/uploads/2026/08/sample.jpg" alt="Sample Image" />
    <ul>
        <li>Item 1</li>
        <li>Item 2</li>
    </ul>
    """
    md_text, success = HtmlToMarkdownConverter.convert(sample_html)
    assert success is True
    assert "## Article Heading" in md_text
    assert "**bold**" in md_text
    assert "*italic*" in md_text
    assert "[link](https://abi.com.vn)" in md_text
    assert "> Wise quote here" in md_text
    assert "```\ndef hello():" in md_text
    assert "![Sample Image](https://abi.com.vn/wp-content/uploads/2026/08/sample.jpg)" in md_text
    assert "- Item 1" in md_text


def test_wp_image_id_extraction():
    html_snippet = '<p><img class="aligncenter size-full wp-image-5878" src="img.jpg" /></p>'
    ids = _extract_wp_image_ids(html_snippet)
    assert ids == [5878]


def test_extract_media_urls():
    html_snippet = '''
    <img src="https://abi.com.vn/wp-content/uploads/2026/08/img1.jpg" srcset="https://abi.com.vn/wp-content/uploads/2026/08/img1-300x200.jpg 300w" />
    <a href="https://abi.com.vn/wp-content/uploads/2026/08/doc.pdf">Document</a>
    '''
    urls = _extract_media_urls(html_snippet)
    assert len(urls) >= 3
    assert any("img1.jpg" in u for u in urls)
    assert any("doc.pdf" in u for u in urls)


def test_normalization_pipeline(tmp_path: Path):
    config = PipelineConfig(workspace_dir=tmp_path / "ws", output_dir=tmp_path / "out")
    config.ensure_directories()

    # Create dummy raw posts and media
    raw_posts = [{
        "id": 101,
        "type": "post",
        "status": "publish",
        "slug": "test-post",
        "link": "https://example.com/test-post",
        "date": "2026-08-16T10:00:00",
        "title": {"rendered": "Test Post Title"},
        "content": {"rendered": '<p>Content with <img class="wp-image-201" src="https://example.com/wp-content/uploads/2026/08/img.jpg" /></p>'},
        "author": 1,
        "featured_media": 202,
        "categories": [10, 20],
        "tags": [30],
    }]

    raw_media = [
        {
            "id": 201,
            "media_type": "image",
            "mime_type": "image/jpeg",
            "source_url": "https://example.com/wp-content/uploads/2026/08/img.jpg",
            "media_details": {"file": "2026/08/img.jpg", "width": 800, "height": 600, "filesize": 12345},
            "post": 101,
        },
        {
            "id": 202,
            "media_type": "image",
            "mime_type": "image/jpeg",
            "source_url": "https://example.com/wp-content/uploads/2026/08/featured.jpg",
            "media_details": {"file": "2026/08/featured.jpg", "width": 1200, "height": 800, "filesize": 54321},
            "post": None,
        }
    ]

    with open(config.raw_dir / "posts_public.json", "w", encoding="utf-8") as f:
        json.dump(raw_posts, f)
    with open(config.raw_dir / "media_public.json", "w", encoding="utf-8") as f:
        json.dump(raw_media, f)

    # 1. Normalize posts
    norm_posts_tool = NormalizePostsTool(config)
    res_p = norm_posts_tool.run()
    assert res_p.success is True

    # 2. Normalize media
    norm_media_tool = NormalizeMediaTool(config)
    res_m = norm_media_tool.run()
    assert res_m.success is True

    # 3. Extract media refs
    extract_tool = ExtractPostMediaTool(config)
    res_e = extract_tool.run()
    assert res_e.success is True

    # 4. Map relations
    map_tool = MapPostMediaTool(config)
    res_map = map_tool.run()
    assert res_map.success is True
    assert res_map.data["featured_count"] == 1
    assert res_map.data["content_count"] == 1
    assert res_map.data["attached_count"] == 1
