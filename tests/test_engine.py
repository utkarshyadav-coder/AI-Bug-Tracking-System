import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pandas as pd
from ai.resolution_engine import KnowledgeBase, ResolutionAdvisor, FallbackSeverity

df = pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "bug_reports_FINAL_v7.csv"))
df = df.where(df.notna(), None)
bugs = df.to_dict("records")
# synthetic resolution notes so the test exercises fix mining
for b in bugs:
    if b["status"] == "Closed":
        b["resolution_notes"] = f"Patched {b['component']} handler and added regression test"

kb = KnowledgeBase(bugs)
adv = ResolutionAdvisor(kb, {"dev_alice": {"component_counts": {"Database": 20}, "avg_resolution": 4,
                                           "reopen_rate": 0.05, "workload": 1}})

def test_similar_found():
    r = adv.advise("Database failed detected", "Database module shows failed", "Database")
    assert r["similar_bugs"] and r["similar_bugs"][0]["component"] == "Database"

def test_unrelated_is_empty():
    r = adv.advise("zzqx plorp", "wibble wobble", None)
    assert r["similar_bugs"] == [] and r["suggested_fixes"] == []

def test_fix_and_eta():
    r = adv.advise("Payment problem detected", "Payment module shows problem", "Payment")
    assert r["suggested_fixes"] and r["eta"]["based_on"] > 0

def test_developer_ranking():
    r = adv.advise("Database failed detected", "Database module shows failed", "Database")
    assert r["recommended_developers"][0]["score"] >= r["recommended_developers"][-1]["score"]

def test_fallback_severity():
    fs = FallbackSeverity(bugs)
    sev, conf = fs.predict("Authentication crash detected", "Authentication module shows crash", "Authentication")
    assert sev in {"Critical", "High", "Medium", "Low"} and 0 < conf <= 1
