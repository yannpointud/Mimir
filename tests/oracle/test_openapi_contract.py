"""
Oracle (a): snapshot of the HTTP contract exposed by the OpenAPI schema.

Pinned per operation: path, method, tags, parameters (name, location,
required flag, schema), request body (content types and fully resolved
schema) and the set of documented status codes. Deliberately excluded:
response schemas (typed later in the cleanup), operation ids, summaries and
descriptions (derived from function names and docstrings), and schema titles
(derived from Python identifiers).
"""

from typing import Any, Dict

from tests.oracle.harness import assert_snapshot

_DROPPED_SCHEMA_KEYS = {"title", "description"}


def _resolve(schema: Any, components: Dict[str, Any], depth: int = 0) -> Any:
    """Inline every $ref and drop naming-only keys."""
    if depth > 20:
        return "<recursion>"
    if isinstance(schema, dict):
        if "$ref" in schema:
            name = schema["$ref"].split("/")[-1]
            return _resolve(components.get(name, {}), components, depth + 1)
        return {
            key: _resolve(value, components, depth + 1)
            for key, value in sorted(schema.items())
            if key not in _DROPPED_SCHEMA_KEYS
        }
    if isinstance(schema, list):
        return [_resolve(item, components, depth + 1) for item in schema]
    return schema


def _contract(openapi: Dict[str, Any]) -> Dict[str, Any]:
    components = openapi.get("components", {}).get("schemas", {})
    contract = {}
    for path, operations in sorted(openapi["paths"].items()):
        for method, operation in sorted(operations.items()):
            parameters = [
                {
                    "name": param["name"],
                    "in": param["in"],
                    "required": param.get("required", False),
                    "schema": _resolve(param.get("schema", {}), components),
                }
                for param in operation.get("parameters", [])
            ]
            parameters.sort(key=lambda p: (p["in"], p["name"]))
            body = operation.get("requestBody")
            request_body = None
            if body:
                request_body = {
                    "required": body.get("required", False),
                    "content": {
                        content_type: _resolve(media.get("schema", {}), components)
                        for content_type, media in sorted(body.get("content", {}).items())
                    },
                }
            contract[f"{method.upper()} {path}"] = {
                "tags": operation.get("tags", []),
                "parameters": parameters,
                "request_body": request_body,
                "status_codes": sorted(operation.get("responses", {}).keys()),
                "security": operation.get("security"),
            }
    return contract


def test_openapi_contract_is_unchanged(oracle_env):
    response = oracle_env.client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert_snapshot("openapi_contract", _contract(response.json()))


def test_openapi_security_scheme_is_unchanged(oracle_env):
    openapi = oracle_env.client.get("/api/v1/openapi.json").json()
    assert_snapshot(
        "openapi_security",
        {
            "security_schemes": openapi["components"].get("securitySchemes"),
            "title": openapi["info"]["title"],
            "version": openapi["info"]["version"],
        },
    )
