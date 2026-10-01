import pandas as pd

from dse_screener.rules import Rule, evaluate


def test_rule_checks():
    assert Rule(min=3).check(5) is None
    assert Rule(min=3).check(2) == "2 < 3"
    assert Rule(max=20.0).check(25.5) == "25.5 > 20"
    assert Rule.model_validate({"in": ["A", "B"]}).check("Z") == "Z not in ['A', 'B']"
    assert Rule(not_in=["Insurance"]).check("Insurance") == "Insurance is excluded"
    assert Rule(not_in=["Insurance"]).check("Bank") is None
    assert Rule(min=0).check(None) == "no data"
    assert Rule(min=0).check(float("nan")) == "no data"


def test_evaluate_collects_all_failures():
    metrics = pd.DataFrame(
        {"category": ["A", "Z"], "dividend_streak": [10, 0]}, index=pd.Index(["GP", "JUNK"], name="code")
    )
    rules = {"category": Rule.model_validate({"in": ["A"]}), "dividend_streak": Rule(min=3)}
    out = evaluate(metrics, rules)
    assert out.loc["GP", "passed"]
    assert not out.loc["JUNK", "passed"]
    assert out.loc["JUNK", "failures"] == ["category: Z not in ['A']", "dividend_streak: 0 < 3"]
