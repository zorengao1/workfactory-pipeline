"""Replay actual observed intents through the revised reviewer."""
import argparse
import hashlib
from pathlib import Path
from workfactory.pipeline.contracts import ROOT
from workfactory.clients.pilot import read_json, save, load_config, run_stage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    case = read_json(ROOT / "fixtures/pilot_cases.json")[0]
    save(out / "metadata.json", {"model": config["OPENAI_MODEL"],
         "template_sha256": hashlib.sha256((ROOT / "prompts/02_intent_review.txt").read_bytes()).hexdigest(),
         "scope": "replay of two observed intents, human-labelled expectations"})
    summary = []
    for version, expected in [("v0", "fail"), ("v1", "pass")]:
        source = ROOT / "runs" / ("pilot-" + version) / "pilot_occupation_001/01a_occupation/parsed.json"
        inputs = {"task_id": "review_replay_" + version, "intent": read_json(source)["result"],
                  "source_materials": case["source_materials"], "constraints": case["constraints"]}
        dest = out / version
        dest.mkdir()
        check, result = run_stage("02_intent_review", inputs, dest, config, 6000)
        verdict = result["verdict"] if result else None
        summary.append({"source": str(source.relative_to(ROOT)), "expected_verdict": expected,
                        "actual_verdict": verdict, "pass": verdict == expected,
                        "validation": check})
        save(out / "summary.json", summary)


if __name__ == "__main__":
    main()
