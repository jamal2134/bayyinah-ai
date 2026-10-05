"""Sanitized Anthropic connectivity diagnostic using Bayyinah's shared configuration."""
import json
import os
import sys
import time
from importlib.metadata import version
from pathlib import Path

import anthropic

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.claim_extractor import ClaimExtractor  # noqa: E402
from app.config.settings import Settings  # noqa: E402


def _error_payload(exc):
    body = getattr(exc, "body", None)
    error = body.get("error", {}) if isinstance(body, dict) else {}
    message = error.get("message") or str(exc)
    # Defensive redaction in case an upstream message unexpectedly echoes a secret.
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        message = message.replace(key, "[REDACTED]")
    return {
        "exception_class": type(exc).__name__,
        "http_status": getattr(exc, "status_code", None),
        "anthropic_error_type": error.get("type"),
        "anthropic_error_message": message[:1000],
        "request_stage": "minimal_messages_create",
    }


def main():
    settings = Settings()
    key = settings.anthropic_api_key
    metadata = {
        "configured_model": settings.anthropic_model,
        "anthropic_sdk_version": version("anthropic"),
        "api_key_present": bool(key),
        "api_key_structurally_present": bool(key and len(key) >= 20 and key.startswith("sk-ant-")),
        "anthropic_base_url_set": bool(os.getenv("ANTHROPIC_BASE_URL")),
        "proxy_environment_variables_set": sorted(name for name in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"
        ) if os.getenv(name)),
        "workspace_id_present": bool(settings.anthropic_workspace_id),
        "timeout_seconds": settings.anthropic_timeout_seconds,
        "application_retry_count": settings.anthropic_max_retries,
    }
    started = time.perf_counter()
    try:
        client = ClaimExtractor(settings).client
        response = client.messages.create(
            model=settings.anthropic_model, max_tokens=8, temperature=0,
            messages=[{"role": "user", "content": "Reply with OK only."}],
        )
        metadata["smoke"] = {
            "status": "PASS", "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "http_status": 200, "model": getattr(response, "model", settings.anthropic_model),
            "usage": ({"input_tokens": response.usage.input_tokens,
                       "output_tokens": response.usage.output_tokens}
                      if getattr(response, "usage", None) else None),
        }
    except Exception as exc:
        metadata["smoke"] = {"status": "FAIL",
                             "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                             **_error_payload(exc)}
    destination = ROOT / "evaluation" / "stage51_anthropic_diagnostic_results.json"
    destination.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
