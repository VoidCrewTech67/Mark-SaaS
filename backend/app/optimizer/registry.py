"""
optimizer/registry.py – Thread-safe pass registry with decorator support.

The ``PassRegistry`` is a singleton that maps pass names (strings) to
``OptimizerPass`` subclasses.  Passes can be registered either
programmatically or via the ``@register_pass`` class decorator.

Usage::

    from app.optimizer.registry import PassRegistry, register_pass

    # Decorator-based registration
    @register_pass
    class MyPass(OptimizerPass): ...

    # Programmatic registration
    registry = PassRegistry()
    registry.register(MyPass)

    # Auto-discover all passes in a package
    registry.discover("app.optimizer.passes")
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
from typing import Dict, List, Type

from app.optimizer.base import OptimizerPass
from app.optimizer.exceptions import PassAlreadyRegisteredError, PassNotFoundError
from app.optimizer.models import PassConfig, PassInfo

logger = logging.getLogger(__name__)


class PassRegistry:
    """Thread-safe singleton registry for optimizer passes.

    The registry maps ``pass.name`` → ``Type[OptimizerPass]``.  Only one
    instance exists per process; repeated instantiation returns the same
    object.
    """

    _instance: PassRegistry | None = None
    _lock: threading.Lock = threading.Lock()

    # ── Singleton ─────────────────────────────────────────────────────────

    def __new__(cls) -> PassRegistry:
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._passes: Dict[str, Type[OptimizerPass]] = {}
                    instance._registry_lock = threading.Lock()
                    cls._instance = instance
        return cls._instance

    # ── Registration ──────────────────────────────────────────────────────

    def register(
        self,
        pass_cls: Type[OptimizerPass],
        *,
        force: bool = False,
    ) -> None:
        """Register an ``OptimizerPass`` subclass.

        Args:
            pass_cls: The pass class to register (must be a concrete subclass
                      of ``OptimizerPass``).
            force:    If True, silently overwrite an existing registration
                      with the same name.

        Raises:
            TypeError: If ``pass_cls`` is not a subclass of ``OptimizerPass``.
            PassAlreadyRegisteredError: If a pass with the same name is already
                registered and ``force`` is False.
        """
        if not (isinstance(pass_cls, type) and issubclass(pass_cls, OptimizerPass)):
            raise TypeError(
                f"Expected a subclass of OptimizerPass, got {pass_cls!r}"
            )

        # Instantiate to read properties (name, description, default_config)
        instance = pass_cls()
        name = instance.name

        with self._registry_lock:
            if name in self._passes and not force:
                raise PassAlreadyRegisteredError(name)

            self._passes[name] = pass_cls
            logger.debug("Registered pass '%s' (%s)", name, pass_cls.__qualname__)

    def unregister(self, name: str) -> None:
        """Remove a pass from the registry.

        Args:
            name: The pass name to remove.

        Raises:
            PassNotFoundError: If no pass with that name is registered.
        """
        with self._registry_lock:
            if name not in self._passes:
                raise PassNotFoundError(name)
            del self._passes[name]
            logger.debug("Unregistered pass '%s'", name)

    # ── Lookup ────────────────────────────────────────────────────────────

    def get(self, name: str) -> Type[OptimizerPass]:
        """Return the pass class registered under ``name``.

        Raises:
            PassNotFoundError: If no pass with that name is registered.
        """
        with self._registry_lock:
            if name not in self._passes:
                raise PassNotFoundError(name)
            return self._passes[name]

    def has(self, name: str) -> bool:
        """Check whether a pass with ``name`` is registered."""
        with self._registry_lock:
            return name in self._passes

    def list_passes(self) -> List[PassInfo]:
        """Return a list of ``PassInfo`` descriptors for all registered passes.

        Each entry contains the pass name, description, and default config
        without instantiating the pass objects more than necessary.
        """
        with self._registry_lock:
            classes = list(self._passes.values())

        result: list[PassInfo] = []
        for cls in classes:
            instance = cls()
            result.append(
                PassInfo(
                    name=instance.name,
                    description=instance.description,
                    default_config=instance.default_config,
                )
            )
        return result

    # ── Auto-discovery ────────────────────────────────────────────────────

    def discover(self, package: str) -> int:
        """Import all modules in ``package`` to trigger ``@register_pass`` decorators.

        Modules whose name starts with ``_`` are skipped (e.g. ``_example.py``).

        Args:
            package: Dotted Python package path (e.g. ``"app.optimizer.passes"``).

        Returns:
            Number of newly registered passes.
        """
        before = len(self._passes)

        try:
            pkg = importlib.import_module(package)
        except ModuleNotFoundError:
            logger.warning("Package '%s' not found; skipping discovery.", package)
            return 0

        pkg_path = getattr(pkg, "__path__", None)
        if pkg_path is None:
            logger.warning("'%s' is not a package; skipping discovery.", package)
            return 0

        for finder, module_name, is_pkg in pkgutil.walk_packages(
            pkg_path, prefix=f"{package}."
        ):
            if module_name.rsplit(".", 1)[-1].startswith("_"):
                continue
            try:
                importlib.import_module(module_name)
                logger.debug("Discovered module '%s'", module_name)
            except Exception:
                logger.exception("Failed to import '%s' during discovery", module_name)

        after = len(self._passes)
        discovered = after - before
        logger.info(
            "Discovery in '%s' found %d new pass(es) (%d total).",
            package, discovered, after,
        )
        return discovered

    # ── Utilities ─────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all registered passes.  **Intended for testing only.**"""
        with self._registry_lock:
            self._passes.clear()
            logger.debug("Registry cleared (all passes removed)")

    @property
    def size(self) -> int:
        """Number of currently registered passes."""
        with self._registry_lock:
            return len(self._passes)

    def __repr__(self) -> str:
        with self._registry_lock:
            names = list(self._passes.keys())
        return f"<PassRegistry passes={names}>"

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def __len__(self) -> int:
        return self.size


# ── Decorator ─────────────────────────────────────────────────────────────────


def register_pass(cls: Type[OptimizerPass]) -> Type[OptimizerPass]:
    """Class decorator that registers an ``OptimizerPass`` subclass.

    Usage::

        @register_pass
        class MyCleanupPass(OptimizerPass):
            ...

    The pass is registered at import time into the global ``PassRegistry``
    singleton.
    """
    PassRegistry().register(cls)
    return cls
