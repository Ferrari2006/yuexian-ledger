import sqlite3
import tempfile
import unittest
from pathlib import Path

from yuexian.store import (
    add_document,
    add_observations,
    append_judgement,
    connect,
    enqueue_job,
    finish_job,
    judgement_history,
)


class StoreTests(unittest.TestCase):
    def test_document_keeps_location_not_body_and_judgements_append(self):
        with tempfile.TemporaryDirectory() as directory:
            database = connect(Path(directory) / "ledger.sqlite")
            document_id = add_document(
                database,
                "SH-1",
                "pdf",
                "objects/SH-1/bl.pdf",
                "review_fallback",
                body=b"not-stored-as-text",
            )
            columns = {row["name"] for row in database.execute("PRAGMA table_info(document)")}
            self.assertNotIn("body", columns)
            add_observations(
                database,
                "SH-1",
                [{"field": "gross_weight_kg", "station": "packing", "value": 12480, "label": "rewrite"}],
                document_id,
            )
            first = {"id": "SH-1", "verdict": "hold", "headline": "先别申报", "blocks": [{"kind": "gross_weight"}], "pending": []}
            second = {"id": "SH-1", "verdict": "send", "headline": "可以申报", "blocks": [], "pending": []}
            append_judgement(database, first, 0.03, rule_version="track2-2026-10")
            append_judgement(database, second, 0.03, rule_version="track2-2026-10")
            history = judgement_history(database, "SH-1")
            self.assertEqual([item["verdict"] for item in history], ["hold", "send"])
            database.close()

    def test_failed_job_stays_as_fallback(self):
        database = connect(":memory:")
        job_id = enqueue_job(database, "SH-2")
        finish_job(database, job_id, "fallback", "pdf 不在本项目解析范围内，已回退为待核验")
        row = database.execute("SELECT status, fallback_reason FROM job WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "fallback")
        self.assertIn("回退", row["fallback_reason"])
        self.assertEqual(database.execute("SELECT COUNT(*) FROM job").fetchone()[0], 1)
        database.close()

    def test_jobs_are_isolated_by_shipment(self):
        database = connect(":memory:")
        enqueue_job(database, "SH-A")
        enqueue_job(database, "SH-B")
        self.assertEqual(
            database.execute("SELECT COUNT(*) FROM job WHERE shipment_id = 'SH-A'").fetchone()[0],
            1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            database.execute("INSERT INTO job (shipment_id, status, created_at) VALUES ('missing', 'pending', 't')")
        database.close()


if __name__ == "__main__":
    unittest.main()
