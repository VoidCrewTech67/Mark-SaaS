"""
optimizer.passes – Concrete optimization passes.

Place each pass in its own module (e.g. ``strip_ocr.py``).  Use the
``@register_pass`` decorator for automatic registration::

    from app.optimizer import OptimizerPass, PassConfig, register_pass

    @register_pass
    class StripOcrArtifacts(OptimizerPass):
        ...

Auto-discovery
~~~~~~~~~~~~~~

Call ``PassRegistry().discover("app.optimizer.passes")`` to import all
modules in this package and trigger registration.  Modules whose names
start with ``_`` (e.g. ``_example.py``) are skipped during discovery.
"""
