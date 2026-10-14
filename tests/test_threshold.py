import copy
import unittest

from yuexian.rules import judge_shipment, load_dataset
from yuexian.pipeline import run_input


class ThresholdTests(unittest.TestCase):
    def setUp(self):
        self.clean = next(copy.deepcopy(s) for s in load_dataset()["shipments"] if judge_shipment(s,.03)["verdict"]=="send")

    def test_invalid_threshold_never_allows_send(self):
        for value in (float("nan"),float("inf"),float("-inf"),True,-.1,1,"0.03",None,10**400):
            with self.subTest(value=value):
                direct=judge_shipment(self.clean,value)
                self.assertEqual(direct["verdict"],"review")
                self.assertTrue(any(p["field"]=="threshold" for p in direct["pending"]))
                self.assertEqual(run_input(self.clean,value)["judgement"]["verdict"],"review")

    def test_valid_threshold_changes_comparison_and_explanation(self):
        item=self.clean
        for obs in item["gross_weight_kg"]:
            if obs["station"]=="packing" and obs.get("label")=="rewrite":
                obs["value"] = next(o["value"] for o in item["gross_weight_kg"] if o["station"]=="bl" and o.get("label")=="rewrite")*1.08
        held=judge_shipment(item,.05)
        self.assertEqual(held["verdict"],"hold")
        self.assertIn("5.0%",next(b for b in held["blocks"] if b["kind"]=="gross_weight")["if_send"])
        self.assertEqual(judge_shipment(item,.1)["verdict"],"send")
