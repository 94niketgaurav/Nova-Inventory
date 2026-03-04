# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
"""
Generates a Postman Collection v2.1 JSON from the FastAPI OpenAPI spec.

Usage:
    uv run python scripts/generate_postman.py > docs/postman_collection.json
    uv run python scripts/generate_postman.py  # writes directly to docs/postman_collection.json
"""
import json
import sys
from pathlib import Path

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app  # noqa: E402 (after sys.path manipulation)


def openapi_to_postman(spec: dict) -> dict:
    """Convert an OpenAPI 3.x spec dict to Postman Collection v2.1 format."""
    info = spec.get("info", {})
    servers = spec.get("servers", [{"url": "http://localhost:8000"}])
    base_url = servers[0]["url"].rstrip("/")

    # Group routes by tag
    folders: dict[str, list] = {}
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            tag = (op.get("tags") or ["default"])[0]
            folders.setdefault(tag, [])

            # Build URL object
            raw_url = base_url + path
            url_obj = {
                "raw": raw_url,
                "host": [base_url],
                "path": [seg.lstrip("/") for seg in path.split("/") if seg],
            }

            # Path variables
            path_vars = [
                {"key": v["name"], "value": f":{v['name']}", "description": v.get("description", "")}
                for v in op.get("parameters", [])
                if v.get("in") == "path"
            ]
            if path_vars:
                url_obj["variable"] = path_vars

            # Query params
            query_params = [
                {"key": v["name"], "value": "", "description": v.get("description", ""), "disabled": not v.get("required", False)}
                for v in op.get("parameters", [])
                if v.get("in") == "query"
            ]
            if query_params:
                url_obj["query"] = query_params

            # Request body
            body = None
            req_body = op.get("requestBody", {})
            if req_body:
                content = req_body.get("content", {})
                json_content = content.get("application/json", {})
                example = _extract_example(json_content, spec)
                body = {
                    "mode": "raw",
                    "raw": json.dumps(example, indent=2) if example else "{}",
                    "options": {"raw": {"language": "json"}},
                }

            # Build headers
            headers = [{"key": "Content-Type", "value": "application/json"}]
            # Auth header (commented out — enable when REQUIRE_AUTH=true)
            headers.append({
                "key": "X-API-Key",
                "value": "{{api_key}}",
                "description": "Required when REQUIRE_AUTH=true",
                "disabled": True,
            })

            item = {
                "name": op.get("summary", f"{method.upper()} {path}"),
                "request": {
                    "method": method.upper(),
                    "header": headers,
                    "url": url_obj,
                    "description": op.get("description", ""),
                },
                "response": [],
            }
            if body:
                item["request"]["body"] = body

            folders[tag].append(item)

    collection_items = [
        {
            "name": tag.title(),
            "item": items,
            "_postman_isSubFolder": False,
        }
        for tag, items in sorted(folders.items())
    ]

    return {
        "info": {
            "name": info.get("title", "Nova Inventory Service"),
            "description": info.get("description", ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "_postman_id": "nova-inventory-v0.1.0",
        },
        "item": collection_items,
        "variable": [
            {"key": "base_url", "value": "http://localhost:8000", "type": "string"},
            {"key": "api_key", "value": "your-api-key-here", "type": "string"},
        ],
        "event": [],
    }


def _extract_example(content: dict, spec: dict) -> dict | None:
    """Try to get an example from the schema — inline example, or a hardcoded fallback."""
    schema = content.get("schema", {})
    # Resolve $ref
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        schema = spec.get("components", {}).get("schemas", {}).get(ref, {})

    # Inline example in schema
    if "example" in schema:
        return schema["example"]

    # Build a minimal example from required properties
    props = schema.get("properties", {})
    required = schema.get("required", [])
    if not props:
        return None

    example = {}
    for field in required or list(props.keys()):
        prop = props.get(field, {})
        ptype = prop.get("type", "string")
        if ptype == "string":
            example[field] = prop.get("example", f"example_{field}")
        elif ptype == "integer":
            example[field] = prop.get("example", 1)
        elif ptype == "number":
            example[field] = prop.get("example", 9.99)
        elif ptype == "boolean":
            example[field] = prop.get("example", False)
        else:
            example[field] = None
    return example


if __name__ == "__main__":
    spec = app.openapi()
    collection = openapi_to_postman(spec)

    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Write Postman collection
    postman_path = docs_dir / "postman_collection.json"
    postman_path.write_text(json.dumps(collection, indent=2))
    print(f"Postman collection written to {postman_path}", file=sys.stderr)

    # Write static OpenAPI snapshot
    openapi_path = docs_dir / "openapi.json"
    openapi_path.write_text(json.dumps(spec, indent=2))
    print(f"OpenAPI spec written to {openapi_path}", file=sys.stderr)
