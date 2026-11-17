"""Recheck saved intents against the final reviewer and planner, plus infeasibility."""
import argparse
import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from workfactory.core.contracts import ROOT
from workfactory.models.client import load_config, read_json, run_stage, save

SOURCES = [
    "runs/pilot-v1/pilot_occupation_001/01a_occupation/parsed.json",
    "runs/skill-retry-v2/pilot_skill_001/01b_skill/parsed.json",
    "runs/pilot-v1/pilot_deliverable_001/01c_deliverable/parsed.json",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    dest = Path(args.output)
    dest.mkdir(parents=True, exist_ok=False)
    cases = read_json(ROOT / "fixtures/pilot_cases.json")
    save(dest / "metadata.json", {
        "model": config["OPENAI_MODEL"], "intent_sources": SOURCES,
        "scope": "three saved generated intents; revised review and planning; one intentionally infeasible variant",
        "hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [ROOT / "workfactory/core/contracts.py", ROOT / "workfactory/models/client.py", ROOT / "workfactory/experiments/final.py",
                             *sorted((ROOT / "prompts").glob("*.txt"))]}})

    def run_case(index):
        case = cases[index]
        folder = dest / case["task_id"]
        folder.mkdir()
        intent = read_json(ROOT / SOURCES[index])["result"]
        inputs = {k: case[k] for k in ["task_id", "source_materials", "constraints"]}
        inputs["intent"] = intent
        outcomes = []
        result, review = run_stage("02_intent_review", inputs, folder, config, 6000)
        outcomes.append(result)
        if review and review["verdict"] == "pass":
            result, plan = run_stage("03_plan", {"task_id": case["task_id"], "intent": intent,
                    "constraints": case["constraints"]}, folder, config, 12000)
            outcomes.append(result)
        summary = {"task_id": case["task_id"], "outcomes": outcomes,
                   "review_verdict": review["verdict"] if review else None,
                   "plan_contract_pass": len(outcomes) == 2 and outcomes[-1]["format_and_contract_pass"]
                         and outcomes[-1]["status"] == "ok"}
        save(folder / "summary.json", summary)
        return summary

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(run_case, range(3)))
    save(dest / "summary.json", results)
    case = copy.deepcopy(cases[0])
    intent = copy.deepcopy(read_json(ROOT / SOURCES[0])["result"])
    intent["objective"] = "必须依据四家真实供应商本月有效的正式报价给出可用于真实签约的采购建议。输入资料未提供任何真实报价，禁止合成、估计、联网和索取补充材料。"
    case["constraints"]["synthesis_allowed"] = False
    case["constraints"]["external_retrieval"] = False
    folder = dest / "negative_unavailable_real_quotes"
    folder.mkdir()
    inputs = {"task_id": folder.name, "intent": intent,
              "source_materials": case["source_materials"], "constraints": case["constraints"]}
    validation, review = run_stage("02_intent_review", inputs, folder, config, 6000)
    save(folder / "summary.json", {"expected_verdict": "fail", "actual_verdict": review["verdict"] if review else None,
         "behavior_pass": bool(review and review["verdict"] == "fail"), "validation": validation})


if __name__ == "__main__":
    main()
