"""
Shared pytest fixtures for the optimizer test suite.

Provides reusable mock passes, configs, and helper factories.
"""

from __future__ import annotations

import pytest

from app.optimizer.base import OptimizerPass
from app.optimizer.exceptions import PassExecutionError
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import PassRegistry


# ── Mock passes ───────────────────────────────────────────────────────────────


class NoOpPass(OptimizerPass):
    """Pass that does nothing — returns content unchanged."""

    @property
    def name(self) -> str:
        return "noop"

    @property
    def description(self) -> str:
        return "Does nothing (test fixture)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(priority=50)

    def run(self, ctx: OptimizationContext, config: PassConfig) -> OptimizationContext:
        return ctx


class UpperCasePass(OptimizerPass):
    """Pass that uppercases all content."""

    @property
    def name(self) -> str:
        return "uppercase"

    @property
    def description(self) -> str:
        return "Convert all content to uppercase (test fixture)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(priority=10)

    def run(self, ctx: OptimizationContext, config: PassConfig) -> OptimizationContext:
        ctx.content = ctx.content.upper()
        return ctx


class AppendPass(OptimizerPass):
    """Pass that appends a configurable suffix."""

    @property
    def name(self) -> str:
        return "append"

    @property
    def description(self) -> str:
        return "Append a suffix to content (test fixture)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(priority=20, params={"suffix": "_appended"})

    def run(self, ctx: OptimizationContext, config: PassConfig) -> OptimizationContext:
        suffix = config.params.get("suffix", "_appended")
        ctx.content = ctx.content + suffix
        return ctx


class StripWhitespacePass(OptimizerPass):
    """Pass that strips leading/trailing whitespace."""

    @property
    def name(self) -> str:
        return "strip_whitespace"

    @property
    def description(self) -> str:
        return "Strip leading/trailing whitespace (test fixture)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(priority=5)

    def run(self, ctx: OptimizationContext, config: PassConfig) -> OptimizationContext:
        ctx.content = ctx.content.strip()
        return ctx


class ErrorPass(OptimizerPass):
    """Pass that always raises an error."""

    @property
    def name(self) -> str:
        return "error_pass"

    @property
    def description(self) -> str:
        return "Always raises an error (test fixture)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(priority=100)

    def run(self, ctx: OptimizationContext, config: PassConfig) -> OptimizationContext:
        raise RuntimeError("Intentional test error")


class DisabledPass(OptimizerPass):
    """Pass that is disabled by default."""

    @property
    def name(self) -> str:
        return "disabled_pass"

    @property
    def description(self) -> str:
        return "Disabled by default (test fixture)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(enabled=False, priority=999)

    def run(self, ctx: OptimizationContext, config: PassConfig) -> OptimizationContext:
        ctx.content = ctx.content + "_SHOULD_NOT_RUN"
        return ctx


class MetadataPass(OptimizerPass):
    """Pass that writes to context metadata."""

    @property
    def name(self) -> str:
        return "metadata_writer"

    @property
    def description(self) -> str:
        return "Writes to metadata (test fixture)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(priority=30)

    def run(self, ctx: OptimizationContext, config: PassConfig) -> OptimizationContext:
        ctx.metadata["metadata_pass_ran"] = True
        ctx.metadata["pass_count"] = ctx.metadata.get("pass_count", 0) + 1
        return ctx


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset the singleton registry before each test."""
    registry = PassRegistry()
    registry.clear()
    yield registry
    registry.clear()


@pytest.fixture
def registry(clean_registry: PassRegistry) -> PassRegistry:
    """Provide a clean PassRegistry."""
    return clean_registry


@pytest.fixture
def registered_noop(registry: PassRegistry) -> NoOpPass:
    """Register and return a NoOpPass."""
    registry.register(NoOpPass)
    return NoOpPass()


@pytest.fixture
def registered_passes(registry: PassRegistry) -> dict[str, type[OptimizerPass]]:
    """Register multiple passes and return a name→class mapping."""
    passes = {
        "noop": NoOpPass,
        "uppercase": UpperCasePass,
        "append": AppendPass,
        "strip_whitespace": StripWhitespacePass,
        "error_pass": ErrorPass,
        "disabled_pass": DisabledPass,
        "metadata_writer": MetadataPass,
    }
    for cls in passes.values():
        registry.register(cls)
    return passes


@pytest.fixture
def sample_content() -> str:
    """Sample markdown content for testing."""
    return (
        "# Hello World\n"
        "\n"
        "This is a test document.\n"
        "\n"
        "## Section Two\n"
        "\n"
        "Some more content here.\n"
    )
