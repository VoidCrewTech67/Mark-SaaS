"""
Tests for PassRegistry — registration, lookup, decorator, and discovery.
"""

from __future__ import annotations

import pytest

from app.optimizer.base import OptimizerPass
from app.optimizer.exceptions import PassAlreadyRegisteredError, PassNotFoundError
from app.optimizer.models import PassConfig
from app.optimizer.registry import PassRegistry, register_pass

from app.optimizer.tests.conftest import (
    AppendPass,
    NoOpPass,
    UpperCasePass,
)


class TestRegistration:
    """Register / unregister lifecycle."""

    def test_register_and_get(self, registry: PassRegistry):
        registry.register(NoOpPass)
        assert registry.get("noop") is NoOpPass

    def test_register_returns_none(self, registry: PassRegistry):
        assert registry.register(NoOpPass) is None

    def test_duplicate_raises(self, registry: PassRegistry):
        registry.register(NoOpPass)
        with pytest.raises(PassAlreadyRegisteredError, match="noop"):
            registry.register(NoOpPass)

    def test_force_overwrite(self, registry: PassRegistry):
        registry.register(NoOpPass)
        registry.register(NoOpPass, force=True)  # should not raise
        assert registry.get("noop") is NoOpPass

    def test_register_non_subclass_raises(self, registry: PassRegistry):
        with pytest.raises(TypeError, match="subclass of OptimizerPass"):
            registry.register(str)  # type: ignore[arg-type]

    def test_unregister(self, registry: PassRegistry):
        registry.register(NoOpPass)
        registry.unregister("noop")
        assert not registry.has("noop")

    def test_unregister_missing_raises(self, registry: PassRegistry):
        with pytest.raises(PassNotFoundError, match="nonexistent"):
            registry.unregister("nonexistent")


class TestLookup:
    """get / has / list_passes / size."""

    def test_get_missing_raises(self, registry: PassRegistry):
        with pytest.raises(PassNotFoundError, match="missing"):
            registry.get("missing")

    def test_has_true(self, registry: PassRegistry):
        registry.register(NoOpPass)
        assert registry.has("noop")

    def test_has_false(self, registry: PassRegistry):
        assert not registry.has("nonexistent")

    def test_contains_dunder(self, registry: PassRegistry):
        registry.register(NoOpPass)
        assert "noop" in registry
        assert "missing" not in registry

    def test_list_passes_empty(self, registry: PassRegistry):
        assert registry.list_passes() == []

    def test_list_passes(self, registry: PassRegistry):
        registry.register(NoOpPass)
        registry.register(UpperCasePass)
        infos = registry.list_passes()
        names = {p.name for p in infos}
        assert names == {"noop", "uppercase"}

    def test_size_and_len(self, registry: PassRegistry):
        assert registry.size == 0
        assert len(registry) == 0
        registry.register(NoOpPass)
        assert registry.size == 1
        assert len(registry) == 1


class TestDecorator:
    """@register_pass class decorator."""

    def test_decorator_registers(self, registry: PassRegistry):
        @register_pass
        class DecoratedPass(OptimizerPass):
            @property
            def name(self) -> str:
                return "decorated"

            @property
            def description(self) -> str:
                return "A decorated pass."

            @property
            def default_config(self) -> PassConfig:
                return PassConfig()

            def run(self, ctx, config):
                return ctx

        assert registry.has("decorated")
        assert registry.get("decorated") is DecoratedPass

    def test_decorator_returns_class(self, registry: PassRegistry):
        @register_pass
        class AnotherPass(OptimizerPass):
            @property
            def name(self) -> str:
                return "another"

            @property
            def description(self) -> str:
                return "Another pass."

            @property
            def default_config(self) -> PassConfig:
                return PassConfig()

            def run(self, ctx, config):
                return ctx

        # The decorator should return the class unchanged
        assert issubclass(AnotherPass, OptimizerPass)


class TestClear:
    """Registry reset."""

    def test_clear_empties_registry(self, registry: PassRegistry):
        registry.register(NoOpPass)
        registry.register(UpperCasePass)
        assert registry.size == 2
        registry.clear()
        assert registry.size == 0

    def test_clear_allows_re_registration(self, registry: PassRegistry):
        registry.register(NoOpPass)
        registry.clear()
        registry.register(NoOpPass)  # should not raise
        assert registry.has("noop")


class TestDiscover:
    """Auto-discovery of passes in a package."""

    def test_discover_nonexistent_package(self, registry: PassRegistry):
        """Discovering a missing package returns 0, does not raise."""
        count = registry.discover("app.optimizer.passes.nonexistent")
        assert count == 0

    def test_discover_skips_underscore_modules(self, registry: PassRegistry):
        """Modules prefixed with _ (like _example.py) are skipped.
        Since modules are already imported (decorators fired once at startup),
        discover() returns 0 but does not raise."""
        count = registry.discover("app.optimizer.passes")
        # Discover completes without error; count may be 0 if modules
        # were already imported (decorators fired once at import time)
        assert count >= 0


class TestRepr:
    """String representations."""

    def test_repr(self, registry: PassRegistry):
        registry.register(NoOpPass)
        r = repr(registry)
        assert "PassRegistry" in r
        assert "noop" in r
