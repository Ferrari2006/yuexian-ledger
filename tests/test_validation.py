import copy
import unittest

from yuexian.extract import extract_document
from yuexian.pipeline import _structure, run_shipment
from yuexian.rules import judge_shipment, load_dataset, weight_gap
from yuexian.weights import parse_weight


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.clean = copy.deepcopy(load_dataset()["shipments"][4])

    def test_empty_input_requires_review(self):
        result = judge_shipment({"id": "EMPTY"}, 0.03)
        self.assertEqual(result["verdict"], "review")
        self.assertEqual(result["headline"], "资料待核验")
        self.assertTrue(result["pending"])

    def test_missing_comparison_fields_never_send(self):
        for field in ("gross_weight_kg", "container_no", "seal_no"):
            for station in (("packing", "bl") if field == "gross_weight_kg" else ("bl", "manifest")):
                with self.subTest(field=field, station=station):
                    shipment = copy.deepcopy(self.clean)
                    shipment[field] = [o for o in shipment[field] if o["station"] != station]
                    self.assertEqual(judge_shipment(shipment, 0.03)["verdict"], "review")

    def test_country_fields_must_be_present(self):
        for field in ("trade", "departure", "origin", "destination"):
            shipment = copy.deepcopy(self.clean)
            shipment["countries"][field] = " "
            self.assertEqual(judge_shipment(shipment, 0.03)["verdict"], "review")

    def test_formatted_kg_is_parsed_and_compared(self):
        for value in ("12,480", "12，480", "12480 kg", "12,480 公斤", "12,480.50 KG"):
            with self.subTest(value=value):
                doc = extract_document(f"单证站点：packing\n毛重（公斤）：{value}\n")
                parsed = doc["observations"]["gross_weight_kg"][0]["value"]
                self.assertIsInstance(parsed, (int, float))
                self.assertGreater(weight_gap(parsed, 12000), 0.03)

    def test_invalid_weights_require_review_instead_of_crashing(self):
        for value in ("12,48", "unknown", "12 t", "NaN", float("nan"),
                      float("inf"), -1, 0, True, 10 ** 400):
            with self.subTest(value=value):
                shipment = copy.deepcopy(self.clean)
                for o in shipment["gross_weight_kg"]:
                    if o["station"] == "bl":
                        o["value"] = value
                self.assertEqual(judge_shipment(shipment, 0.03)["verdict"], "review")
                self.assertIsNone(weight_gap(1500, value))

    def test_conflict_remains_hold_when_other_fields_are_missing(self):
        shipment = copy.deepcopy(load_dataset()["shipments"][0])
        shipment["seal_no"] = []
        result = judge_shipment(shipment, 0.03)
        self.assertEqual(result["verdict"], "hold")
        self.assertTrue(result["blocks"])
        self.assertTrue(result["pending"])

    def test_empty_pipeline_explanation_does_not_claim_consistency(self):
        result = run_shipment({"id": "EMPTY"}, 0.03)
        self.assertEqual(result["judgement"]["verdict"], "review")
        self.assertNotIn("毛重与提单一致", result["explanation"])
        self.assertIn("请核验", result["explanation"])

    def test_structure_cannot_recover_missing_countries_from_gold(self):
        result = _structure(self.clean, [extract_document("单证站点：bl\n票号：X\n")])
        self.assertEqual(result["countries"], {})
        self.assertEqual(judge_shipment(result, 0.03)["verdict"], "review")

    def test_unknown_unit_is_not_silently_converted(self):
        self.assertIsNone(parse_weight("12 tonnes"))
        self.assertEqual(parse_weight("1,500 kilograms"), 1500)

    def test_weight_formatting_does_not_shift_first_difference(self):
        shipment = copy.deepcopy(load_dataset()["shipments"][0])
        shipment["gross_weight_kg"][0]["value"] = "12,000 kg"
        result = judge_shipment(shipment, 0.03)
        weight = next(b for b in result["blocks"] if b["kind"] == "gross_weight")
        self.assertEqual(weight["birth_station"], "packing")


if __name__ == "__main__":
    unittest.main()
