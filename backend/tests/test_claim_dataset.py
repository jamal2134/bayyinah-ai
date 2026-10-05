import json
from pathlib import Path


def test_dataset_has_30_diverse_cases():
    path = Path(__file__).parents[2] / "evaluation" / "claim_extraction_dataset.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    assert len(items) >= 35
    assert len({item["input_text"] for item in items}) == len(items)
    for item in items:
        expected = item["expected"]
        assert expected["minimum_claim_count"] >= 0
        assert expected["maximum_claim_count"] >= expected["minimum_claim_count"]
        assert expected["domains"] and expected["claim_types"]
        assert "key_propositions" in expected

