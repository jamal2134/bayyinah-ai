import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))


def valid_result(claims=None, language="en"):
    claims = claims or []
    return {"input_language": language, "claim_count": len(claims), "claims": claims}


def claim(identifier="claim_001", text="Ayat al-Kursi is verse 255 of al-Baqarah.", claim_type="QURAN_REFERENCE", domain="QURAN"):
    return {"id": identifier, "original_text": text, "normalized_claim": text,
            "claim_type": claim_type, "domain": domain, "search_queries": [text],
            "entities": [], "requires_evidence": True, "reason": "Externally verifiable proposition."}


class FakeMessages:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(output, ensure_ascii=False) if isinstance(output, dict) else output)])


class FakeClient:
    def __init__(self, outputs):
        self.messages = FakeMessages(outputs)


@pytest.fixture
def settings():
    from app.config.settings import Settings
    return Settings(anthropic_api_key="test-key", anthropic_model="test-model", anthropic_max_retries=1)

