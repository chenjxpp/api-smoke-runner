"""Regression tests for collection validation and response assertions.

The covered contract is documented in ``docs/architecture-overview.md``.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api_smoke_runner import ConfigError, ResponseData, load_cases, run_suite


class SmokeRunnerTests(unittest.TestCase):
    """Verify normalization, assertions, and failure isolation."""

    def test_environment_expansion_and_successful_assertions(self) -> None:
        """Variables expand before a fake transport satisfies all assertions."""

        cases = load_cases(
            {
                "requests": [
                    {
                        "name": "health",
                        "url": "${BASE_URL}/health",
                        "headers": {"Authorization": "Bearer ${TOKEN}"},
                        "expect": {"status": [200, 204], "body_contains": "ok", "json_equals": {"service.ready": True}},
                    }
                ]
            },
            {"BASE_URL": "https://service.test", "TOKEN": "secret"},
        )

        def fake_transport(case):
            self.assertEqual(case.url, "https://service.test/health")
            self.assertEqual(case.headers["Authorization"], "Bearer secret")
            return ResponseData(200, b'{"message":"ok","service":{"ready":true}}')

        result = run_suite(cases, fake_transport)
        self.assertTrue(result.ok)
        self.assertNotIn("secret", str(result.to_dict()))

    def test_assertion_failures_are_all_reported(self) -> None:
        """Status, substring, and JSON-value failures remain visible together."""

        cases = load_cases(
            {
                "requests": [
                    {
                        "name": "bad response",
                        "url": "https://service.test",
                        "expect": {"status": 200, "body_contains": "ready", "json_equals": {"ok": True}},
                    }
                ]
            }
        )
        result = run_suite(cases, lambda case: ResponseData(503, b'{"ok":false}'))
        self.assertFalse(result.ok)
        self.assertEqual(len(result.cases[0].failures), 3)

    def test_missing_environment_variable_is_a_config_error(self) -> None:
        """An unresolved placeholder fails early instead of sending a bad URL."""

        with self.assertRaises(ConfigError):
            load_cases({"requests": [{"name": "x", "url": "${MISSING}/x"}]}, {})

    def test_transport_exception_does_not_abort_suite(self) -> None:
        """Transport failures become case results suitable for diagnosis."""

        cases = load_cases({"requests": [{"name": "x", "url": "https://service.test"}]})

        def broken_transport(case):
            raise TimeoutError("too slow")

        result = run_suite(cases, broken_transport)
        self.assertFalse(result.ok)
        self.assertIn("TimeoutError", result.cases[0].failures[0])


if __name__ == "__main__":
    unittest.main()
