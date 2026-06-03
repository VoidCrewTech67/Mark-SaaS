"""
optimizer/config.py – Pipeline configuration loader.

``PipelineConfig`` defines which passes to run, in what order, and with
what per-pass overrides.  It can be constructed from a Python dict, loaded
from a YAML file (if PyYAML is installed), or built programmatically.

Usage::

    config = PipelineConfig(
        pass_order=["unicode_normalize", "strip_ocr_artifacts", "deduplicate"],
        pass_configs={
            "deduplicate": PassConfig(params={"scope": "section"}),
        },
    )

    # Or from a dict (e.g. parsed from an API request body):
    config = PipelineConfig.from_dict({
        "pass_order": ["unicode_normalize"],
        "fail_fast": False,
    })
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.optimizer.models import PassConfig

logger = logging.getLogger(__name__)


class PipelineConfig(BaseModel):
    """Configuration for a complete pipeline execution.

    Attributes:
        pass_order:         Ordered list of pass names to execute.  An empty
                            list means "no passes" (input returned as-is).
        pass_configs:       Per-pass configuration overrides, keyed by pass
                            name.  These are merged on top of each pass's
                            ``default_config`` at execution time.
        fail_fast:          If True (default), the pipeline stops at the first
                            pass that raises an exception.  If False, errors
                            are collected and the pipeline continues.
        collect_statistics: If True (default), the executor records timing
                            and token counts for every pass.  Disable for
                            maximum throughput in hot paths.
    """

    pass_order: List[str] = Field(default_factory=list)
    pass_configs: Dict[str, PassConfig] = Field(default_factory=dict)
    fail_fast: bool = True
    collect_statistics: bool = True

    # ── Validators ────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_pass_configs_reference_known_passes(self) -> PipelineConfig:
        """Warn if pass_configs references names not in pass_order.

        This is a soft warning (not an error) because configs may be
        pre-populated for passes that are only sometimes included.
        """
        order_set = set(self.pass_order)
        for name in self.pass_configs:
            if name not in order_set:
                logger.warning(
                    "PipelineConfig has config for pass '%s' which is not in "
                    "pass_order %s. It will be ignored.",
                    name,
                    self.pass_order,
                )
        return self

    # ── Factory methods ───────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PipelineConfig:
        """Build a ``PipelineConfig`` from a plain dictionary.

        The ``pass_configs`` values can be either ``PassConfig`` instances
        or plain dicts (which will be validated by Pydantic).

        Args:
            data: Configuration dictionary.

        Returns:
            A validated ``PipelineConfig`` instance.
        """
        # Normalise pass_configs dicts → PassConfig instances
        raw_configs = data.get("pass_configs", {})
        normalised: Dict[str, PassConfig] = {}
        for name, cfg in raw_configs.items():
            if isinstance(cfg, dict):
                normalised[name] = PassConfig.model_validate(cfg)
            elif isinstance(cfg, PassConfig):
                normalised[name] = cfg
            else:
                raise TypeError(
                    f"pass_configs['{name}'] must be a dict or PassConfig, "
                    f"got {type(cfg).__name__}"
                )
        data = {**data, "pass_configs": normalised}
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: Path | str) -> PipelineConfig:
        """Load a ``PipelineConfig`` from a YAML file.

        Requires ``PyYAML`` to be installed.  If it is not available,
        raises ``ImportError`` with an actionable message.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A validated ``PipelineConfig`` instance.

        Raises:
            ImportError: If PyYAML is not installed.
            FileNotFoundError: If the file does not exist.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required to load YAML configs. "
                "Install it with: pip install pyyaml"
            ) from None

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        logger.info("Loaded pipeline config from '%s'", path)
        return cls.from_dict(data)

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary (JSON-compatible)."""
        return self.model_dump(mode="json")

    # ── Helpers ───────────────────────────────────────────────────────────

    def get_pass_config(self, pass_name: str) -> Optional[PassConfig]:
        """Return the override config for ``pass_name``, or None."""
        return self.pass_configs.get(pass_name)

    def with_pass_order(self, order: List[str]) -> PipelineConfig:
        """Return a copy with a different pass order."""
        return self.model_copy(update={"pass_order": order})

    def __repr__(self) -> str:
        return (
            f"PipelineConfig(passes={self.pass_order}, "
            f"fail_fast={self.fail_fast}, "
            f"statistics={self.collect_statistics})"
        )
