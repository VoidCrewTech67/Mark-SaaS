"""
Tests for PipelineConfig — construction, factories, validation.
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import PassConfig


class TestPipelineConfigDefaults:
    """Default values and basic construction."""

    def test_empty_config(self):
        cfg = PipelineConfig()
        assert cfg.pass_order == []
        assert cfg.pass_configs == {}
        assert cfg.fail_fast is True
        assert cfg.collect_statistics is True

    def test_custom_pass_order(self):
        cfg = PipelineConfig(pass_order=["a", "b", "c"])
        assert cfg.pass_order == ["a", "b", "c"]

    def test_custom_pass_configs(self):
        cfg = PipelineConfig(
            pass_order=["my_pass"],
            pass_configs={
                "my_pass": PassConfig(enabled=False, params={"key": "val"}),
            },
        )
        assert cfg.pass_configs["my_pass"].enabled is False
        assert cfg.pass_configs["my_pass"].params["key"] == "val"


class TestFromDict:
    """PipelineConfig.from_dict() factory."""

    def test_basic_from_dict(self):
        data = {
            "pass_order": ["alpha", "beta"],
            "fail_fast": False,
        }
        cfg = PipelineConfig.from_dict(data)
        assert cfg.pass_order == ["alpha", "beta"]
        assert cfg.fail_fast is False

    def test_from_dict_with_pass_configs_as_dicts(self):
        data = {
            "pass_order": ["x"],
            "pass_configs": {
                "x": {"enabled": True, "priority": 5, "params": {"a": 1}},
            },
        }
        cfg = PipelineConfig.from_dict(data)
        assert isinstance(cfg.pass_configs["x"], PassConfig)
        assert cfg.pass_configs["x"].priority == 5
        assert cfg.pass_configs["x"].params["a"] == 1

    def test_from_dict_with_pass_configs_as_objects(self):
        data = {
            "pass_order": ["y"],
            "pass_configs": {
                "y": PassConfig(priority=42),
            },
        }
        cfg = PipelineConfig.from_dict(data)
        assert cfg.pass_configs["y"].priority == 42

    def test_from_dict_invalid_pass_config_type(self):
        data = {
            "pass_order": ["z"],
            "pass_configs": {"z": "not_a_config"},
        }
        with pytest.raises(TypeError, match="dict or PassConfig"):
            PipelineConfig.from_dict(data)


class TestToDict:
    """Serialization round-trip."""

    def test_round_trip(self):
        cfg = PipelineConfig(
            pass_order=["a", "b"],
            pass_configs={"a": PassConfig(priority=1)},
            fail_fast=False,
            collect_statistics=False,
        )
        d = cfg.to_dict()
        assert d["pass_order"] == ["a", "b"]
        assert d["fail_fast"] is False
        assert d["collect_statistics"] is False
        assert d["pass_configs"]["a"]["priority"] == 1

    def test_round_trip_from_dict(self):
        original = {
            "pass_order": ["x"],
            "pass_configs": {"x": {"enabled": False}},
            "fail_fast": True,
        }
        cfg = PipelineConfig.from_dict(original)
        d = cfg.to_dict()
        assert d["pass_order"] == ["x"]
        assert d["pass_configs"]["x"]["enabled"] is False


class TestValidation:
    """Validator warnings for orphaned configs."""

    def test_orphaned_config_warns(self, caplog):
        """pass_configs referencing names not in pass_order should warn."""
        import logging

        with caplog.at_level(logging.WARNING, logger="app.optimizer.config"):
            PipelineConfig(
                pass_order=["a"],
                pass_configs={"b": PassConfig()},  # 'b' not in pass_order
            )
        assert any("'b'" in record.message for record in caplog.records)


class TestHelpers:
    """Helper methods."""

    def test_get_pass_config_found(self):
        cfg = PipelineConfig(
            pass_order=["x"],
            pass_configs={"x": PassConfig(priority=7)},
        )
        pc = cfg.get_pass_config("x")
        assert pc is not None
        assert pc.priority == 7

    def test_get_pass_config_missing(self):
        cfg = PipelineConfig(pass_order=["x"])
        assert cfg.get_pass_config("x") is None

    def test_with_pass_order(self):
        cfg = PipelineConfig(pass_order=["a", "b"])
        new_cfg = cfg.with_pass_order(["c", "d"])
        assert new_cfg.pass_order == ["c", "d"]
        assert cfg.pass_order == ["a", "b"]  # original unchanged

    def test_repr(self):
        cfg = PipelineConfig(pass_order=["a"])
        r = repr(cfg)
        assert "PipelineConfig" in r
        assert "'a'" in r
