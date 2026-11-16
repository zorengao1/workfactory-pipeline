import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import ROOT
from pilot import run_stage


class RuntimeRecordingTest(unittest.TestCase):
    def test_connection_failure_is_recorded_and_redacted(self):
        case = json.loads((ROOT / "fixtures/pilot_cases.json").read_text())[0]
        inputs = {k: case[k] for k in ["task_id", "source_materials", "constraints"]}
        config = {"OPENAI_MODEL": "fixture-model", "OPENAI_API_KEY": "fixture-secret"}
        with tempfile.TemporaryDirectory() as folder:
            with patch("pilot.complete", side_effect=ConnectionError("failed fixture-secret")):
                with self.assertRaises(ConnectionError):
                    run_stage(case["stage"], inputs, Path(folder), config, 100)
            raw = (Path(folder) / case["stage"] / "transport_error.json").read_text()
            self.assertNotIn("fixture-secret", raw)
            self.assertIn("[REDACTED]", raw)
            self.assertFalse(json.loads(raw)["accepted_for_pipeline"])


if __name__ == "__main__":
    unittest.main()
