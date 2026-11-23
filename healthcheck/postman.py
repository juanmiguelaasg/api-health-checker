"""Postman integration: import collections to YAML, export YAML as a Postman/Newman collection."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import yaml

from .config import ENV_PATTERN, Config

POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
PM_VAR = re.compile(r"\{\{([^{}]+)\}\}")


# ---------------------------------------------------------------- export ---
def _to_postman_vars(text: str, variables: dict[str, str]) -> str:
    """${VAR:-default} -> {{VAR}}; the default is stored as a collection variable."""
    def repl(m: re.Match) -> str:
        variables.setdefault(m.group(1), m.group(2) or "")
        return "{{" + m.group(1) + "}}"
    return ENV_PATTERN.sub(repl, text)


def export_collection(config: Config, name: str = "API Health-Checker") -> dict:
    variables: dict[str, str] = {}
    items = []
    for ep in config.endpoints:
        codes = json.dumps(ep.expected_status)
        tests = [
            f'pm.test("Status code {codes}", function () {{\n'
            f'    pm.expect(pm.response.code).to.be.oneOf({codes});\n}});',
            f'pm.test("Response time < {ep.max_response_ms} ms", function () {{\n'
            f'    pm.expect(pm.response.responseTime).to.be.below({ep.max_response_ms});\n}});',
        ]
        for needle in ep.contains:
            tests.append(f'pm.test({json.dumps("Body contains: " + needle, ensure_ascii=False)}, function () {{\n'
                         f'    pm.expect(pm.response.text()).to.include({json.dumps(needle, ensure_ascii=False)});\n}});')
        if ep.schema is not None:
            tests.append(f"const schema = {json.dumps(ep.schema, ensure_ascii=False)};\n"
                         'pm.test("JSON schema", function () {\n    pm.response.to.have.jsonSchema(schema);\n});')

        request: dict[str, Any] = {
            "method": ep.method,
            "header": [{"key": k, "value": _to_postman_vars(v, variables)} for k, v in ep.raw_headers.items()],
            "url": _to_postman_vars(ep.raw_url or ep.url, variables),
        }
        if ep.body is not None:
            raw = json.dumps(ep.body, ensure_ascii=False, indent=2) if isinstance(ep.body, (dict, list)) else str(ep.body)
            request["body"] = {"mode": "raw", "raw": raw, "options": {"raw": {"language": "json"}}}

        items.append({
            "name": ep.name,
            "request": request,
            "event": [{"listen": "test", "script": {"type": "text/javascript",
                                                     "exec": "\n\n".join(tests).split("\n")}}],
        })

    return {
        "info": {"_postman_id": str(uuid.uuid4()), "name": name, "schema": POSTMAN_SCHEMA,
                 "description": "Generated from endpoints.yaml (healthcheck postman-export)."},
        "item": items,
        "variable": [{"key": k, "value": v} for k, v in variables.items()],
    }


# ---------------------------------------------------------------- import ---
def _url_of(req: dict) -> str:
    url = req.get("url", "")
    if isinstance(url, str):
        return url
    if url.get("raw"):
        return url["raw"]
    host = ".".join(url.get("host") or [])
    path = "/".join(url.get("path") or [])
    proto = url.get("protocol", "https")
    return f"{proto}://{host}/{path}"


def _expectations(script: str) -> dict:
    out: dict[str, Any] = {}
    codes = [int(c) for c in re.findall(r"to\.have\.status\(\s*(\d{3})\s*\)", script)]
    codes += [int(c) for c in re.findall(r"response\.code\)\.to\.(?:eql|equal|eq)\(\s*(\d{3})\s*\)", script)]
    for group in re.findall(r"to\.be\.oneOf\(\s*\[([\d,\s]+)\]\s*\)", script):
        codes += [int(c) for c in re.findall(r"\d{3}", group)]
    if codes:
        out["expected_status"] = sorted(set(codes)) if len(set(codes)) > 1 else codes[0]
    m = re.search(r"responseTime\)\.to\.be\.(?:below|lessThan)\(\s*(\d+)\s*\)", script)
    if m:
        out["max_response_ms"] = int(m.group(1))
    m = re.search(r"const\s+schema\s*=\s*(\{.*?\});\s*\n", script, re.S)
    if m:
        try:
            out["schema"] = json.loads(m.group(1))
        except ValueError:
            pass
    contains = re.findall(r'text\(\)\)\.to\.include\(\s*"((?:[^"\\]|\\.)*)"\s*\)', script)
    if contains:
        out["contains"] = [json.loads(f'"{c}"') for c in contains]
    return out


def import_collection(collection: dict, environment: dict | None = None) -> dict:
    variables = {v["key"]: str(v.get("value", "")) for v in collection.get("variable", []) if "key" in v}
    if environment:
        variables.update({v["key"]: str(v.get("value", "")) for v in environment.get("values", [])
                          if v.get("enabled", True) and "key" in v})

    def to_env(text: str) -> str:
        return PM_VAR.sub(lambda m: "${%s:-%s}" % (m.group(1), variables.get(m.group(1), ""))
                          if variables.get(m.group(1)) else "${%s}" % m.group(1), text)

    endpoints: list[dict] = []

    def walk(items: list, prefix: str) -> None:
        for it in items:
            if "item" in it:
                walk(it["item"], f"{prefix}{it.get('name', '')} / ")
                continue
            req = it.get("request")
            if not req:
                continue
            if isinstance(req, str):
                req = {"url": req, "method": "GET"}
            ep: dict[str, Any] = {"name": prefix + it.get("name", "Unnamed"),
                                  "url": to_env(_url_of(req)),
                                  "method": req.get("method", "GET")}
            headers = {h["key"]: to_env(str(h.get("value", ""))) for h in req.get("header", [])
                       if not h.get("disabled")}
            if headers:
                ep["headers"] = headers
            body = req.get("body") or {}
            if body.get("mode") == "raw" and body.get("raw"):
                try:
                    ep["body"] = json.loads(body["raw"])
                except ValueError:
                    ep["body"] = body["raw"]
            script = "\n".join(
                "\n".join(e["script"]["exec"]) if isinstance(e["script"].get("exec"), list) else e["script"].get("exec", "")
                for e in it.get("event", []) if e.get("listen") == "test" and e.get("script"))
            ep.update(_expectations(script + "\n"))
            ep.setdefault("expected_status", 200)
            endpoints.append(ep)

    walk(collection.get("item", []), "")
    return {"endpoints": endpoints}


def import_to_yaml(collection_path: Path, out_path: Path, env_path: Path | None = None,
                   settings: dict | None = None) -> int:
    coll = json.loads(Path(collection_path).read_text(encoding="utf-8"))
    env = json.loads(Path(env_path).read_text(encoding="utf-8")) if env_path else None
    doc = import_collection(coll, env)
    if settings:
        doc = {"settings": settings, **doc}
    Path(out_path).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return len(doc["endpoints"])


# ---------------------------------------------------------------- newman ---
def run_newman(collection_path: Path, junit_path: Path | None = None, env: dict[str, str] | None = None) -> int:
    exe = shutil.which("newman")
    cmd = [exe] if exe else ([shutil.which("npx"), "--yes", "newman"] if shutil.which("npx") else None)
    if not cmd:
        raise RuntimeError("Newman not found. Install it with: npm install -g newman")
    cmd += ["run", str(collection_path), "--reporters", "cli,junit" if junit_path else "cli"]
    if junit_path:
        cmd += ["--reporter-junit-export", str(junit_path)]
    for k, v in (env or {}).items():
        cmd += ["--env-var", f"{k}={v}"]
    return subprocess.call(cmd)
