# api-smoke-runner

A dependency-free Python CLI for running small HTTP API smoke suites from a
reviewable JSON file. It is useful for local checks, deployment gates, and
minimal CI jobs where a full test framework would be excessive.

## Features

- GET, POST, PUT, PATCH, DELETE, and other HTTP methods supported by `urllib`;
- request headers and JSON request bodies;
- `${ENV_NAME}` substitution without storing secrets in the collection;
- expected status, body substring, and JSON-path equality checks;
- readable console output or a JSON report;
- non-zero exit status for failed checks or invalid configuration.

## Quick start

```bash
python -m api_smoke_runner examples/example.json
```

A collection contains a `requests` array:

```json
{
  "requests": [
    {
      "name": "service health",
      "method": "GET",
      "url": "${BASE_URL}/health",
      "headers": {"Authorization": "Bearer ${API_TOKEN}"},
      "timeout_seconds": 5,
      "expect": {
        "status": 200,
        "body_contains": "ok",
        "json_equals": {"service.ready": true}
      }
    }
  ]
}
```

Variables must already exist in the process environment. The runner never
prints request headers or environment-variable values, reducing accidental
secret disclosure in CI logs.

## Assertions

- `status` accepts one integer or an array such as `[200, 204]`.
- `body_contains` accepts one string or an array; every string must occur.
- `json_equals` maps dotted object paths to expected JSON values.

Run with `--json` for a machine-readable report. Exit codes are `0` for a clean
suite, `1` when one or more requests/checks fail, and `2` for invalid collection
or I/O errors.

## Development

```bash
python -m unittest discover -s tests -v
```

See [`docs/architecture-overview.md`](docs/architecture-overview.md) for public
contracts, call flow, and extension points.

## License

MIT
