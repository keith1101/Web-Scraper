"""Tests for media validation, recovery tool, and error classifications."""

import json
from pathlib import Path
import pytest
from src.config import PipelineConfig
from src.tools.recovery import RecoverMissingMediaTool, ValidateMediaTool


def test_media_recovery_and_classification(tmp_path: Path):
    config = PipelineConfig(
        source_url="https://abi.com.vn",
        workspace_dir=tmp_path / "ws",
        output_dir=tmp_path / "out",
    )
    config.ensure_directories()

    # 1 valid file, 1 missing file, 1 zero-byte file
    valid_path = config.workspace_media_dir / "2026/08/valid.jpg"
    valid_path.parent.mkdir(parents=True, exist_ok=True)
    with open(valid_path, "wb") as f:
        f.write(b"VALID_IMAGE")

    zero_path = config.workspace_media_dir / "2026/08/zero.jpg"
    with open(zero_path, "wb") as f:
        pass  # 0 bytes

    media = [
        {
            "id": 1,
            "relative_path": "2026/08/valid.jpg",
            "source_url": "https://abi.com.vn/wp-content/uploads/2026/08/valid.jpg",
            "file_exists": True,
        },
        {
            "id": 2,
            "relative_path": "2026/08/zero.jpg",
            "source_url": "https://abi.com.vn/wp-content/uploads/2026/08/zero.jpg",
            "file_exists": False,
        },
        {
            "id": 3,
            "relative_path": "2026/08/missing.jpg",
            "source_url": "https://abi.com.vn/wp-content/uploads/2026/08/missing.jpg",
            "file_exists": False,
        },
    ]

    with open(config.normalized_dir / "media.json", "w", encoding="utf-8") as f:
        json.dump(media, f)
    with open(config.normalized_dir / "post_media_mapping.json", "w", encoding="utf-8") as f:
        json.dump([], f)

    val_tool = ValidateMediaTool(config)
    res_val = val_tool.run()
    assert res_val.success is True
    assert res_val.data["valid_files"] == 1
    assert res_val.data["zero_byte_files"] == 1
    assert res_val.data["missing_files"] == 1

    rec_tool = RecoverMissingMediaTool(config)
    res_rec = rec_tool.run()
    assert res_rec.success is True
