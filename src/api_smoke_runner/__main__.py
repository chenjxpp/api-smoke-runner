"""Module entry point for ``python -m api_smoke_runner``.

See ``docs/architecture-overview.md`` for the package call flow.
"""

from .cli import main

raise SystemExit(main())
