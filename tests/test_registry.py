"""Tests for Tool Registry, metadata validation, and version bumping."""

import pytest
from src.agent.registry import ToolMetadata, ToolRegistry, ToolStatus


def test_registry_registration_and_lookup():
    reg = ToolRegistry()

    class SampleTool:
        metadata = ToolMetadata(
            name="sample_scraper",
            version="1.0.0",
            description="A sample tool for testing",
            capabilities=["testing", "sample"],
            status=ToolStatus.READY,
        )

    reg.register(SampleTool)
    assert reg.get("sample_scraper") is SampleTool
    meta = reg.get_metadata("sample_scraper")
    assert meta is not None
    assert meta.name == "sample_scraper"
    assert meta.version == "1.0.0"
    assert "testing" in meta.capabilities


def test_registry_capability_search():
    reg = ToolRegistry()

    class ToolA:
        metadata = ToolMetadata(
            name="tool_a",
            version="1.0.0",
            description="Tool A",
            capabilities=["wordpress", "posts"],
        )

    class ToolB:
        metadata = ToolMetadata(
            name="tool_b",
            version="1.0.0",
            description="Tool B",
            capabilities=["wordpress", "media"],
        )

    reg.register(ToolA)
    reg.register(ToolB)

    wp_tools = reg.find_by_capability("wordpress")
    assert len(wp_tools) == 2
    post_tools = reg.find_by_capability("posts")
    assert len(post_tools) == 1
    assert post_tools[0].name == "tool_a"


def test_registry_version_bumping():
    reg = ToolRegistry()

    class ToolA:
        metadata = ToolMetadata(
            name="tool_a",
            version="1.0.0",
            description="Tool A",
        )

    reg.register(ToolA)
    new_v = reg.bump_version("tool_a", "patch")
    assert new_v == "1.0.1"

    new_v = reg.bump_version("tool_a", "minor")
    assert new_v == "1.1.0"

    new_v = reg.bump_version("tool_a", "major")
    assert new_v == "2.0.0"
