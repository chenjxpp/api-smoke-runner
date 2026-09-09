"""Configuration, transport, and assertions for HTTP API smoke tests.

This module is independent of console and file I/O. The full call flow and
extension contract are documented in ``docs/architecture-overview.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """Signal an invalid collection field or unresolved environment variable."""


@dataclass(frozen=True)
class RequestCase:
    """Hold one normalized request and its response expectations.

    ``body_json`` is encoded only at transport time. ``expect_status`` always
    contains at least one accepted status. ``expect_json`` maps dotted object
    paths to exact expected values.
    """

    name: str
    method: str
    url: str
    headers: dict[str, str]
    body_json: Any | None
    timeout_seconds: float
    expect_status: tuple[int, ...]
    expect_contains: tuple[str, ...]
    expect_json: dict[str, Any]


@dataclass(frozen=True)
class ResponseData:
    """Represent the transport-neutral response used by assertions."""

    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass
class CaseResult:
    """Record response metadata and assertion failures for one case.

    Response bodies and request headers are deliberately excluded from the
    serialized result to avoid leaking tokens or sensitive payloads in logs.
    """

    name: str
    ok: bool
    status: int | None
    duration_ms: int
    failures: list[str]


@dataclass
class SuiteResult:
    """Aggregate case results and expose success/failure counts."""

    cases: list[CaseResult]

    @property
    def ok(self) -> bool:
        """Return ``True`` when every request and assertion passed."""

        return all(case.ok for case in self.cases)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable suite report without request secrets."""

        passed = sum(1 for case in self.cases if case.ok)
        return {
            "ok": self.ok,
            "total": len(self.cases),
            "passed": passed,
            "failed": len(self.cases) - passed,
            "cases": [asdict(case) for case in self.cases],
        }


Transport = Callable[[RequestCase], ResponseData]


def _expand(value: Any, environ: Mapping[str, str]) -> Any:
    """Recursively expand explicit ``${NAME}`` placeholders in JSON values."""

    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            if variable not in environ:
                raise ConfigError(f"environment variable {variable} is not set")
            return environ[variable]

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand(item, environ) for item in value]
    if isinstance(value, dict):
        return {str(key): _expand(item, environ) for key, item in value.items()}
    return value


def _status_tuple(value: Any, case_name: str) -> tuple[int, ...]:
    """Normalize one status or a list of statuses into a validated tuple."""

    statuses = value if isinstance(value, list) else [value]
    if not statuses or any(not isinstance(status, int) for status in statuses):
        raise ConfigError(f"{case_name}: expect.status must be an integer or non-empty integer array")
    return tuple(statuses)


def _string_tuple(value: Any, field_name: str, case_name: str) -> tuple[str, ...]:
    """Normalize one assertion string or list of strings into a tuple."""

    if value is None:
        return ()
    strings = value if isinstance(value, list) else [value]
    if any(not isinstance(item, str) for item in strings):
        raise ConfigError(f"{case_name}: {field_name} must be a string or string array")
    return tuple(strings)


def load_cases(payload: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> list[RequestCase]:
    """Validate raw collection data and return normalized request cases.

    The entire payload is environment-expanded before validation. Unknown
    fields remain ignored so collection metadata can be added without changing
    the execution contract.
    """

    expanded = _expand(dict(payload), environ if environ is not None else os.environ)
    raw_cases = expanded.get("requests")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ConfigError("collection must contain a non-empty 'requests' array")

    cases: list[RequestCase] = []
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, dict):
            raise ConfigError(f"request {index} must be an object")
        name = raw.get("name")
        url = raw.get("url")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"request {index} requires a non-empty name")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ConfigError(f"{name}: url must begin with http:// or https://")
        headers = raw.get("headers", {})
        if not isinstance(headers, dict) or any(not isinstance(v, str) for v in headers.values()):
            raise ConfigError(f"{name}: headers must map names to strings")
        expect = raw.get("expect", {})
        if not isinstance(expect, dict):
            raise ConfigError(f"{name}: expect must be an object")
        expect_json = expect.get("json_equals", {})
        if not isinstance(expect_json, dict):
            raise ConfigError(f"{name}: expect.json_equals must be an object")
        timeout = raw.get("timeout_seconds", 10)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ConfigError(f"{name}: timeout_seconds must be positive")

        cases.append(
            RequestCase(
                name=name.strip(),
                method=str(raw.get("method", "GET")).upper(),
                url=url,
                headers={str(key): value for key, value in headers.items()},
                body_json=raw.get("body_json"),
                timeout_seconds=float(timeout),
                expect_status=_status_tuple(expect.get("status", 200), name),
                expect_contains=_string_tuple(expect.get("body_contains"), "expect.body_contains", name),
                expect_json=dict(expect_json),
            )
        )
    return cases


def default_transport(case: RequestCase) -> ResponseData:
    """Execute one normalized request with Python's standard-library ``urllib``."""

    headers = dict(case.headers)
    body: bytes | None = None
    if case.body_json is not None:
        body = json.dumps(case.body_json, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = Request(case.url, data=body, headers=headers, method=case.method)
    try:
        with urlopen(request, timeout=case.timeout_seconds) as response:
            return ResponseData(response.status, response.read(), dict(response.headers.items()))
    except HTTPError as exc:
        return ResponseData(exc.code, exc.read(), dict(exc.headers.items()) if exc.headers else {})


def _json_path(value: Any, dotted_path: str) -> Any:
    """Resolve a dot-separated object path and raise ``KeyError`` when absent."""

    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def run_case(case: RequestCase, transport: Transport = default_transport) -> CaseResult:
    """Execute one case and evaluate all configured response assertions."""

    started = time.perf_counter()
    try:
        response = transport(case)
    except Exception as exc:  # Transport adapters define their own exception types.
        duration_ms = round((time.perf_counter() - started) * 1000)
        return CaseResult(case.name, False, None, duration_ms, [f"transport error: {type(exc).__name__}: {exc}"])

    duration_ms = round((time.perf_counter() - started) * 1000)
    failures: list[str] = []
    if response.status not in case.expect_status:
        failures.append(f"status {response.status} not in expected {list(case.expect_status)}")

    text = response.body.decode("utf-8", errors="replace")
    for expected_text in case.expect_contains:
        if expected_text not in text:
            failures.append(f"body does not contain {expected_text!r}")

    if case.expect_json:
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            failures.append(f"response is not valid JSON: {exc.msg}")
        else:
            for path, expected_value in case.expect_json.items():
                try:
                    actual_value = _json_path(document, path)
                except KeyError:
                    failures.append(f"JSON path {path!r} is missing")
                else:
                    if actual_value != expected_value:
                        failures.append(f"JSON path {path!r} is {actual_value!r}, expected {expected_value!r}")

    return CaseResult(case.name, not failures, response.status, duration_ms, failures)


def run_suite(cases: list[RequestCase], transport: Transport = default_transport) -> SuiteResult:
    """Run all cases sequentially and retain every failure for diagnosis."""

    return SuiteResult([run_case(case, transport) for case in cases])
