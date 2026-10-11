import unittest
from unittest.mock import patch

from yuexian.extract import extract_document
from yuexian.pipeline import run_dataset, run_shipment
from yuexian.rules import judge_shipment, load_dataset


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_dataset()

    def test_document_extract_reads_weight(self):
        text = "单证站点：packing\n票号：X\n毛重（公斤）：12480\n扫描毛重（公斤）：99999\n"
        parsed = extract_document(text)
        labels = [item["label"] for item in parsed["observations"]["gross_weight_kg"]]
        self.assertEqual(labels, ["rewrite", "ocr_error"])

    def test_pipeline_verdict_matches_gold(self):
        threshold = self.dataset["threshold_gross_weight"]
        for shipment in self.dataset["shipments"]:
            gold = judge_shipment(shipment, threshold)
            ran = run_shipment(shipment, threshold)
            self.assertEqual(ran["judgement"]["verdict"], gold["verdict"], shipment["id"])
            self.assertEqual(ran["judgement"]["headline"], gold["headline"], shipment["id"])
            self.assertEqual(ran["judgement"], gold, shipment["id"])
            stages = [step["stage"] for step in ran["trace"]]
            self.assertEqual(stages, ["ingest", "extract", "structure", "decide", "explain"])

    def test_hero_explanation_keeps_hold(self):
        hero = next(item for item in self.dataset["shipments"] if item["demo"])
        ran = run_shipment(hero, 0.03)
        self.assertIn("先别申报", ran["explanation"])
        self.assertIn("装箱单", ran["documents"]["packing"])
        self.assertIn("12480", ran["documents"]["packing"])
        self.assertIn("12000", ran["documents"]["bl"])

    def test_dataset_run_covers_every_shipment(self):
        ran = run_dataset(self.dataset)
        self.assertEqual(len(ran), len(self.dataset["shipments"]))

    def test_birth_is_only_inferred_from_available_history(self):
        import copy

        hero = copy.deepcopy(self.dataset["shipments"][0])
        full = run_shipment(hero, 0.03)
        weight = next(b for b in full["judgement"]["blocks"] if b["kind"] == "gross_weight")
        self.assertEqual(weight["birth_station"], "packing")
        self.assertIn("booking", full["documents"])
        hero["gross_weight_kg"] = [o for o in hero["gross_weight_kg"] if o["station"] != "booking"]
        partial = run_shipment(hero, 0.03)
        weight = next(b for b in partial["judgement"]["blocks"] if b["kind"] == "gross_weight")
        self.assertEqual(weight["birth_station"], "bl")
        self.assertNotIn("booking", partial["documents"])

    def test_qwen_status_reports_outcome_without_changing_decision(self):
        shipment = self.dataset["shipments"][0]
        baseline = run_shipment(shipment, 0.03)
        self.assertEqual(baseline["trace"][1]["qwen_status"], "disabled")
        outcomes = [
            (None, "not_configured"),
            ({"source": "qwen", "error": "network error"}, "failed"),
            ({"source": "qwen", "raw": ""}, "failed"),
            ({"source": "qwen", "raw": "arbitrary response"}, "response_received"),
        ]
        for response, status in outcomes:
            with self.subTest(status=status, response=response):
                with patch("yuexian.pipeline.extract_with_qwen", return_value=response) as call:
                    result = run_shipment(shipment, 0.03, use_qwen=True)
                call.assert_called_once()
                self.assertEqual(result["trace"][1]["qwen_status"], status)
                self.assertEqual(result["judgement"], baseline["judgement"])
                self.assertEqual(result["explanation"], baseline["explanation"])

    def test_disabled_qwen_does_not_call_model(self):
        with patch("yuexian.pipeline.extract_with_qwen") as call:
            run_shipment(self.dataset["shipments"][0], 0.03)
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
