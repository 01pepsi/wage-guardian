"""임금 계산 엔진 테스트: py -m pytest -v"""
import json
from pathlib import Path
import pytest
from wage_calc import WageInput, calculate

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case(case):
    result = calculate(WageInput(**case["input"]))

    if "expected_missing" in case:
        assert result.ok is False
        assert result.missing == case["expected_missing"]
        return

    assert result.ok is True
    assert result.total_shortfall == case["expected_total"]
    violated = sorted(i.code for i in result.items if i.violated)
    assert violated == sorted(case["expected_violations"])