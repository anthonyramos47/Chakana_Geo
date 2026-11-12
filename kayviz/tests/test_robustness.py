"""kayviz.evaluate robustness checks, each in a fresh process. The slow ones run
with `pytest -m slow` (tools/check.sh py -m slow)."""

import pytest

from kayviz.evaluate import robustness as R


@pytest.mark.parametrize("check", [
    pytest.param(c, marks=pytest.mark.slow) if c in R.SLOW else c for c in R.CHECKS])
def test_robustness(check):
    res = R.run_check(check)
    assert res["pass"], res["detail"]
