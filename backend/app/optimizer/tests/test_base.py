"""
Tests for OptimizerPass abstract base class contract.
"""

from __future__ import annotations

import pytest

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig


class TestOptimizerPassABC:
    """Verify the ABC contract enforcement."""

    def test_cannot_instantiate_abc_directly(self):
        """OptimizerPass itself cannot be instantiated."""
        with pytest.raises(TypeError, match="abstract"):
            OptimizerPass()  # type: ignore[abstract]

    def test_must_implement_name(self):
        """Subclass missing 'name' property cannot be instantiated."""

        class MissingName(OptimizerPass):
            @property
            def description(self) -> str:
                return "test"

            @property
            def default_config(self) -> PassConfig:
                return PassConfig()

            def run(self, ctx, config):
                return ctx

        with pytest.raises(TypeError, match="abstract"):
            MissingName()  # type: ignore[abstract]

    def test_must_implement_description(self):
        """Subclass missing 'description' property cannot be instantiated."""

        class MissingDesc(OptimizerPass):
            @property
            def name(self) -> str:
                return "test"

            @property
            def default_config(self) -> PassConfig:
                return PassConfig()

            def run(self, ctx, config):
                return ctx

        with pytest.raises(TypeError, match="abstract"):
            MissingDesc()  # type: ignore[abstract]

    def test_must_implement_default_config(self):
        """Subclass missing 'default_config' property cannot be instantiated."""

        class MissingConfig(OptimizerPass):
            @property
            def name(self) -> str:
                return "test"

            @property
            def description(self) -> str:
                return "test"

            def run(self, ctx, config):
                return ctx

        with pytest.raises(TypeError, match="abstract"):
            MissingConfig()  # type: ignore[abstract]

    def test_must_implement_run(self):
        """Subclass missing 'run' method cannot be instantiated."""

        class MissingRun(OptimizerPass):
            @property
            def name(self) -> str:
                return "test"

            @property
            def description(self) -> str:
                return "test"

            @property
            def default_config(self) -> PassConfig:
                return PassConfig()

        with pytest.raises(TypeError, match="abstract"):
            MissingRun()  # type: ignore[abstract]


class TestConcretePass:
    """Verify behaviour of a fully-implemented concrete pass."""

    def test_concrete_pass_instantiates(self, registered_noop):
        """A concrete pass implementing all abstracts can be created."""
        assert registered_noop.name == "noop"
        assert registered_noop.description
        assert isinstance(registered_noop.default_config, PassConfig)

    def test_validate_config_is_noop_by_default(self, registered_noop):
        """Default validate_config does not raise."""
        registered_noop.validate_config(PassConfig())

    def test_run_returns_context(self, registered_noop):
        """run() should return the OptimizationContext."""
        ctx = OptimizationContext(content="hello", original_content="hello")
        result = registered_noop.run(ctx, PassConfig())
        assert isinstance(result, OptimizationContext)
        assert result.content == "hello"

    def test_repr_and_str(self, registered_noop):
        """__repr__ and __str__ produce sensible output."""
        assert "noop" in repr(registered_noop)
        assert str(registered_noop) == "noop"
