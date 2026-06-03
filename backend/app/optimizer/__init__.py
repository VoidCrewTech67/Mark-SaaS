"""
app.optimizer – Modular Markdown optimization framework.

Public API
~~~~~~~~~~

Core abstractions::

    from app.optimizer import OptimizerPass, register_pass

Data models::

    from app.optimizer import (
        PassConfig, PassStatistics, OptimizationContext,
        PipelineResult, PipelineReport, PassInfo,
    )

Orchestration::

    from app.optimizer import PassRegistry, PipelineExecutor, PipelineConfig

Exceptions::

    from app.optimizer import (
        OptimizationError, PassNotFoundError, PassAlreadyRegisteredError,
        PassConfigError, PassExecutionError, PipelineError,
    )
"""

from app.optimizer.base import OptimizerPass
from app.optimizer.config import PipelineConfig
from app.optimizer.exceptions import (
    OptimizationError,
    PassAlreadyRegisteredError,
    PassConfigError,
    PassExecutionError,
    PassNotFoundError,
    PipelineError,
)
from app.optimizer.models import (
    OptimizationContext,
    PassConfig,
    PassInfo,
    PassStatistics,
    PipelineReport,
    PipelineResult,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry, register_pass
from app.optimizer.report import ReportGenerator

__all__ = [
    # ABC
    "OptimizerPass",
    # Decorator
    "register_pass",
    # Models
    "PassConfig",
    "PassStatistics",
    "OptimizationContext",
    "PipelineResult",
    "PipelineReport",
    "PassInfo",
    # Orchestration
    "PassRegistry",
    "PipelineExecutor",
    "PipelineConfig",
    "ReportGenerator",
    # Exceptions
    "OptimizationError",
    "PassNotFoundError",
    "PassAlreadyRegisteredError",
    "PassConfigError",
    "PassExecutionError",
    "PipelineError",
]
