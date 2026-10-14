import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from yuexian.documents import render_shipment
from yuexian.intake import run_documents
from yuexian.pipeline import run_shipment, run_batch
from yuexian.rules import judge_shipment, load_dataset


def bundle_for(shipment):
    return {"id":shipment["id"],"title":shipment.get("title", ""),
            "documents":[{"name":f"{station}.txt","station":station,"text":text}
                         for station,text in render_shipment(shipment).items()]}


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.dataset=load_dataset()
        self.clean=next(s for s in self.dataset["shipments"] if judge_shipment(s,.03)["verdict"]=="send")
        self.bundle=bundle_for(self.clean)

    def test_fixture_verdicts_match_existing_pipeline(self):
        for shipment in self.dataset["shipments"]:
            with self.subTest(id=shipment["id"]):
                original=run_shipment(shipment,.03)["judgement"]
                result=run_documents(bundle_for(shipment))["judgement"]
                self.assertEqual(result["verdict"],original["verdict"])
                self.assertEqual(result["blocks"],original["blocks"])

    def test_original_lines_are_exact_evidence(self):
        result=run_documents(self.bundle)
        for field in result["evidence"]:
            original=result["documents"][field["document"]].splitlines()[field["line"]-1]
            self.assertEqual(field["raw"],original)
        self.assertTrue(any(e["field"]=="gross_weight_kg" for e in result["evidence"]))

    def test_mixed_shipment_id_cannot_send(self):
        self.bundle["documents"][0]["text"]=self.bundle["documents"][0]["text"].replace(self.clean["id"],"OTHER")
        result=run_documents(self.bundle)
        self.assertEqual(result["judgement"]["verdict"],"review")
        self.assertTrue(any(p["field"]=="shipment_id" for p in result["judgement"]["pending"]))

    def test_country_conflict_cannot_be_overwritten_into_send(self):
        doc=self.bundle["documents"][0]
        doc["text"] += "最终目的国：different-country\n"
        result=run_documents(self.bundle)
        self.assertEqual(result["judgement"]["verdict"],"review")
        self.assertTrue(any(p["field"]=="destination" for p in result["judgement"]["pending"]))

    def test_conflicting_duplicate_field_requires_review(self):
        doc=next(d for d in self.bundle["documents"] if d["station"]=="bl")
        original=doc["text"]
        doc["text"]="毛重（公斤）：1\n"+original
        self.assertEqual(run_documents(self.bundle)["judgement"]["verdict"],"review")

    def test_wrong_declared_station_requires_review(self):
        self.bundle["documents"][0]["text"] += "单证站点：other\n"
        self.assertNotEqual(run_documents(self.bundle)["judgement"]["verdict"],"send")

    def test_missing_station_can_use_declared_metadata(self):
        for doc in self.bundle["documents"]:
            doc["text"]="\n".join(line for line in doc["text"].splitlines() if not line.startswith("单证站点："))
        self.assertEqual(run_documents(self.bundle)["judgement"]["verdict"],"send")

    def test_known_hold_is_not_downgraded_by_identity_issue(self):
        shipment=next(s for s in self.dataset["shipments"] if judge_shipment(s,.03)["verdict"]=="hold")
        bundle=bundle_for(shipment)
        bundle["documents"][0]["text"] += "票号：OTHER\n"
        judged=run_documents(bundle)["judgement"]
        self.assertEqual(judged["verdict"],"hold")
        self.assertTrue(judged["pending"])

    def test_schema_errors_are_explicit(self):
        for bundle in (None,{}, {"id":"X","documents":[]}, {"id":"X","documents":[{"name":"x","station":"pdf","text":""}]}):
            with self.subTest(bundle=bundle),self.assertRaises(ValueError):
                run_documents(bundle)

    def test_batch_preserves_order_and_isolates_invalid_bundle(self):
        invalid=copy.deepcopy(self.bundle)
        invalid.update(id="BAD",documents=[])
        results=run_batch([self.bundle,invalid,self.bundle],.03,workers=2)
        self.assertEqual([r["id"] for r in results],[self.clean["id"],"BAD",self.clean["id"]])
        self.assertEqual([r["judgement"]["verdict"] for r in results],["send","review","send"])

    def test_cli_reads_bom_and_writes_json(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"input.json"
            target=Path(directory)/"output.json"
            source.write_text(json.dumps(self.bundle,ensure_ascii=False),encoding="utf-8-sig")
            result=subprocess.run([sys.executable,"-m","yuexian","check","--input",str(source),"--output",str(target)],
                                  capture_output=True,text=True,encoding="utf-8",env={**os.environ,"PYTHONIOENCODING":"utf-8","PYTHONPATH":str(Path(__file__).resolve().parents[1]/"src")})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["judgement"]["verdict"],"send")
