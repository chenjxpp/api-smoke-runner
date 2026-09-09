"""Public API for api-smoke-runner.

See ``docs/architecture-overview.md`` for the normalized collection contract,
transport interface, and result model.
"""

from .core import (
    CaseResult,
    ConfigError,
    RequestCase,
    ResponseData,
    SuiteResult,
    load_cases,
    run_suite,
)

__all__ = [
    "CaseResult",
    "ConfigError",
    "RequestCase",
    "ResponseData",
    "SuiteResult",
    "load_cases",
    "run_suite",
]
