#!/usr/bin/env python3
"""Verify the configured local Ollama provider without contacting OpenAI."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.run import (
    CONFIG_PATH,
    build_ollama_request_body,
    canonical_json,
    sha256_bytes,
)
from harness.scoring import parse_model_content


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    messages = [
        {
            "role": "developer",
            "content": (
                "Return exactly this JSON object and nothing else: "
                '{"output_type":"ANSWER","answer_text":"SMOKE_OK",'
                '"citations":["smoke"],"confidence":0.1}'
            ),
        },
        {"role": "user", "content": "Smoke-test the local provider."},
    ]
    request_body = build_ollama_request_body(config, messages)
    request_bytes = canonical_json(request_body).encode("utf-8")
    url = config["ollama"]["api_base_url"].rstrip("/") + "/api/chat"
    request = urllib.request.Request(
        url,
        data=request_bytes,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "abstention-study-ollama-smoke/1.0.0",
        },
    )
    started = time.perf_counter()
    status: int | None = None
    response_bytes = b""
    error: str | None = None
    try:
        with urllib.request.urlopen(
            request, timeout=float(config["api_timeout_seconds"])
        ) as response:
            status = int(response.status)
            response_bytes = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        response_bytes = exc.read()
        error = f"HTTPError:{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}:{exc}"
    latency_ms = int(round((time.perf_counter() - started) * 1000))
    response_text = response_bytes.decode("utf-8", errors="replace")
    response_json: dict[str, object] | None = None
    try:
        parsed = json.loads(response_text) if response_text else None
        if isinstance(parsed, dict):
            response_json = parsed
    except json.JSONDecodeError:
        error = error or "invalid_json_response"

    content = None
    parse_error = None
    parsed_output = None
    if response_json and isinstance(response_json.get("message"), dict):
        content_value = response_json["message"].get("content")
        if isinstance(content_value, str):
            content = content_value
            parsed_output, parse_error = parse_model_content(content)
    if status != 200:
        error = error or f"http_{status}"
    if content is None:
        error = error or "missing_message_content"
    if parsed_output is None:
        error = error or f"invalid_contract:{parse_error}"

    output_path = REPO_ROOT / "results" / "runs" / "ollama_smoke.json"
    atomic_write(
        output_path,
        {
            "schema_version": "1.0.0",
            "provider": "ollama",
            "endpoint": url,
            "model": config["ollama"]["model"],
            "checked_at_utc": utc_now(),
            "http_status": status,
            "latency_ms": latency_ms,
            "request_body": request_body,
            "request_body_sha256": sha256_bytes(request_bytes),
            "response_body_raw": response_text,
            "response_body_sha256": sha256_bytes(response_bytes),
            "response_content": content,
            "contract_valid": parsed_output is not None,
            "error": error,
        },
    )
    print(json.dumps({"smoke_path": str(output_path), "error": error}, sort_keys=True))
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main())
