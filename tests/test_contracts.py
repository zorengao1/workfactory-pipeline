import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workfactory.pipeline.contracts import (ROOT, STAGES, REQUIRED_CHECKS, input_errors, output_errors,
                       output_schema, plan_errors, render, validate)


def minimal_plan():
    return {
        "user_request": "读取输入单价，计算两件商品总价并保存结果。",
        "nodes": [
            {"id": "n1", "content": "单价", "entity": "商品", "scope": "当前", "unit": "元",
             "provision": "supplied", "value": "5", "construction_spec": None, "provenance": "synthetic",
             "carrier_ids": ["c1"]},
            {"id": "n2", "content": "两件总价", "entity": "商品", "scope": "当前", "unit": "元",
             "provision": "derived", "value": None, "construction_spec": None, "provenance": "solver",
             "carrier_ids": ["c2"]}],
        "carriers": [
            {"id": "c1", "kind": "reference", "location": "input.txt", "visible": True},
            {"id": "c2", "kind": "deliverable", "location": "result.txt", "visible": True}],
        "relations": [{"sources": ["n1"], "target": "n2", "relation": "乘二"}],
        "reference_files": [{"id": "f1", "path": "input.txt", "format": "txt", "role": "input",
                              "node_ids": ["n1"], "provenance": "synthetic", "method": "synthesize",
                              "depends_on": []}],
        "deliverable_requirements": [{"id": "d1", "description": "两件总价", "node_ids": ["n2"]}]}


class ContractsTest(unittest.TestCase):
    def test_generated_material_is_distinct_from_fixed_value(self):
        plan = minimal_plan()
        plan["nodes"][0]["construction_spec"] = "生成六条已授权的合成商品单价记录"
        self.assertTrue(any("exactly one" in e for e in plan_errors(plan)))
        plan["nodes"][0]["value"] = None
        self.assertFalse(plan_errors(plan))

    def test_derived_value_leak(self):
        plan = minimal_plan()
        self.assertFalse(plan_errors(plan))
        plan["nodes"][1]["value"] = "10"
        self.assertTrue(any("value exposed" in e for e in plan_errors(plan)))

    def test_input_binding_leak(self):
        plan = minimal_plan()
        plan["nodes"][1]["carrier_ids"] = ["c1"]
        self.assertTrue(any("bound as supplied" in e for e in plan_errors(plan)))

    def test_hidden_required_input(self):
        plan = minimal_plan()
        plan["carriers"][0]["visible"] = False
        self.assertTrue(any("lacks visible" in e for e in plan_errors(plan)))

    def test_file_cycle_and_dangling_reference(self):
        plan = minimal_plan()
        plan["reference_files"][0]["depends_on"] = ["f1"]
        self.assertIn("cyclic file dependency", plan_errors(plan))
        plan["reference_files"][0]["depends_on"] = ["missing"]
        self.assertIn("unknown file dependency", plan_errors(plan))

    def test_review_contradiction(self):
        checks = [{"criterion": k, "passed": True, "evidence": ["source"], "reason": "checked"}
                  for k in REQUIRED_CHECKS["02_intent_review"]]
        checks[0]["passed"] = False
        value = {"task_id": "t", "status": "ok", "result": {"verdict": "pass", "checks": checks}, "issues": []}
        self.assertIn("verdict contradicts checks", output_errors("02_intent_review", value, {"task_id": "t"}))

    def test_plan_honors_file_constraints(self):
        value = {"task_id": "t", "status": "ok", "result": minimal_plan(), "issues": []}
        errors = output_errors("03_plan", value, {"task_id": "t", "constraints": {
            "reference_file_count": 2, "allowed_reference_formats": ["pdf"]}})
        self.assertIn("reference file count differs from constraints", errors)
        self.assertIn("reference format outside allowed formats", errors)

    def test_probe_and_teacher_reject_internal_top_level(self):
        for stage in ["06_probe", "09_teacher"]:
            data = {"task_id": "t", "environment": {"user_request": "x", "reference_files": [], "resources": []},
                    "workspace": {}, "initial_plan": {"secret": "answer"}}
            self.assertTrue(input_errors(stage, data))
            del data["initial_plan"]
            self.assertFalse(input_errors(stage, data))
            data["environment"]["diagnoses"] = ["hidden"]
            self.assertTrue(input_errors(stage, data))

    def test_blocked_requires_reason_and_null_result(self):
        value = {"task_id": "t", "status": "blocked", "result": None, "issues": ["source absent"]}
        self.assertFalse(validate(value, output_schema("03_plan")))
        value["issues"] = []
        self.assertTrue(validate(value, output_schema("03_plan")))

    def test_strict_unknown_fields_and_boolean(self):
        value = {"task_id": "t", "status": "rejected", "result": None, "issues": ["unsupported"], "extra": 1}
        self.assertTrue(validate(value, output_schema("03_plan")))
        self.assertTrue(validate(1, {"type": "boolean"}))

    def test_render_and_five_blocks(self):
        cases = json.loads((ROOT / "fixtures/pilot_cases.json").read_text())
        for stage in STAGES:
            text = (ROOT / "prompts" / (stage + ".txt")).read_text()
            self.assertEqual(text.count("【"), 5)
        for case in cases:
            data = {k: case[k] for k in ["task_id", "source_materials", "constraints"]}
            messages = render(case["stage"], data)
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["content"].count("【"), 5)
            self.assertNotIn(case["source_materials"][0]["content"], messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
