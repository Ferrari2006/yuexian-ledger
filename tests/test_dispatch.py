import unittest
from unittest.mock import patch

from yuexian.dispatch import classify
from yuexian.pipeline import run_ballast, run_batch, run_input, run_shipment
from yuexian.preprocess import preprocess_text
from yuexian.rules import load_dataset


class PreprocessTests(unittest.TestCase):
    def test_noise_lines_are_removed_and_weight_remains(self):
        text = "第 1 页\n----\n单证站点：packing\n票号：X\n毛重（公斤）：12,480 kg\n"
        cleaned = preprocess_text(text)
        self.assertEqual(cleaned["fallback"], "none")
        self.assertGreater(cleaned["dropped_noise"], 0)
        self.assertNotIn("第 1 页", cleaned["text"])
        self.assertIn("毛重（公斤）：12,480 kg", cleaned["text"])

    def test_noise_filter_rolls_back_when_it_would_erase_fields(self):
        text = "毛重（公斤）：12480 水印\n"
        cleaned = preprocess_text(text)
        self.assertEqual(cleaned["fallback"], "noise_filter")
        self.assertIn("毛重（公斤）：12480 水印", cleaned["text"])

    def test_missing_document_does_not_raise(self):
        cleaned = preprocess_text("只有标题，没有栏位")
        self.assertEqual(cleaned["fallback"], "missing")
        self.assertEqual(cleaned["missing"], ["document"])


class DispatchTests(unittest.TestCase):
    def test_file_types_use_different_handlers(self):
        self.assertEqual(classify("单证站点：packing\n毛重（公斤）：1\n"), "text/form")
        self.assertEqual(classify({"id": "S", "countries": {}, "gross_weight_kg": []}), "json/shipment")
        self.assertEqual(classify({"id": "P", "input_type": "pdf"}), "unsupported")
        self.assertEqual(classify({"id": "H", "file_type": "hs"}), "unsupported")

    def test_unsupported_type_falls_back_without_extract(self):
        with patch("yuexian.pipeline.extract_document") as extract:
            result = run_input({"id": "P-1", "input_type": "pdf", "title": "证书扫描"}, 0.03)
        extract.assert_not_called()
        self.assertEqual(result["judgement"]["verdict"], "review")
        self.assertEqual(result["judgement"]["headline"], "资料待核验")
        self.assertEqual(result["trace"][0]["handler"], "review_fallback")
        self.assertIn("pdf", result["explanation"])

    def test_broken_record_falls_back_instead_of_raising(self):
        result = run_input({"gross_weight_kg": []}, 0.03)
        self.assertEqual(result["judgement"]["verdict"], "review")
        self.assertIn("回退", result["explanation"])

    def test_batch_keeps_order_and_same_verdicts(self):
        dataset = load_dataset()
        items = []
        for shipment in dataset["shipments"]:
            items.append(shipment)
            items.append({"id": f"{shipment['id']}-pdf", "input_type": "image"})
        batch = run_batch(items, dataset["threshold_gross_weight"], workers=3)
        self.assertEqual([item["id"] for item in batch], [item["id"] if isinstance(item, dict) else "" for item in items])
        for source, ran in zip(items, batch):
            if source.get("input_type") == "image":
                self.assertEqual(ran["judgement"]["verdict"], "review")
            else:
                self.assertEqual(ran["judgement"], run_shipment(source, 0.03)["judgement"])

    def test_ballast_keeps_verdicts_and_counts_fallbacks(self):
        report = run_ballast(load_dataset(), copies=3, workers=4, bad_every=5)
        self.assertTrue(report["stable"])
        self.assertGreater(report["fallbacks"], 0)
        self.assertEqual(report["mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
