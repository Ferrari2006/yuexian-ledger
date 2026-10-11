import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import verify_submission as verifier


class VerifierTests(unittest.TestCase):
    def check_modified_payload(self, name, mutate):
        html = verifier.DEMO.read_text(encoding="utf-8")
        pattern = r"const " + name + r" = (.*?);\s*\n"
        matched = re.search(pattern, html, re.S)
        payload = json.loads(matched.group(1))
        mutate(payload)
        html = html[:matched.start(1)] + json.dumps(payload, ensure_ascii=False) + html[matched.end(1):]
        with tempfile.TemporaryDirectory() as directory:
            demo = Path(directory) / "index.html"
            demo.write_text(html, encoding="utf-8")
            with patch.object(verifier, "DEMO", demo), contextlib.redirect_stdout(io.StringIO()) as output:
                code = verifier.main()
        self.assertEqual(code, 1, output.getvalue())
        return output.getvalue()

    def test_stale_verdict_detected_with_unchanged_footer(self):
        output = self.check_modified_payload("DATA", lambda data: data["shipments"][0].update(verdict="send"))
        self.assertIn("逐票判定", output)

    def test_stale_explanation_detected_with_unchanged_footer(self):
        output = self.check_modified_payload("FLOWS", lambda flows: next(iter(flows.values())).update(explanation="可以申报"))
        self.assertIn("轨迹或解释", output)

    def test_invalid_statistic_fails_cleanly(self):
        output = self.check_modified_payload("DATA", lambda data: data.update(weight_hold_count="invalid"))
        self.assertIn("weight_hold_count", output)

    def test_invalid_shipments_fails_cleanly(self):
        output = self.check_modified_payload("DATA", lambda data: data.update(shipments=None))
        self.assertIn("逐票判定", output)
