import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SubmissionTests(unittest.TestCase):
    """交稿前机器可验证的项（docs/提交清单.md 的可自动化部分）。

    清单里「页脚三个数由规则复算、不是手填的」原本只是一句声称。
    这里把它变成会失败的断言 —— 数字漂移时先在本地红掉，
    而不是等到评审现场。
    """

    CHECKED = (
        "birth_station_ratio",
        "birth_station_hit",
        "birth_station_total",
        "country_mix_count",
        "weight_hold_count",
    )

    def _demo_data(self) -> dict:
        path = ROOT / "demo" / "index.html"
        self.assertTrue(path.exists(), "demo/index.html 不存在，先跑 build_demo")
        html = path.read_text(encoding="utf-8")
        match = re.search(r"const DATA = (\{.*?\});\s*\n", html, re.S)
        self.assertIsNotNone(match, "demo/index.html 里找不到内嵌 DATA")
        return json.loads(match.group(1))

    def test_demo_footer_numbers_match_rule_recomputation(self):
        from yuexian.rules import load_dataset, score

        data = self._demo_data()
        expected = score(load_dataset())
        for key in self.CHECKED:
            with self.subTest(key=key):
                self.assertIn(key, data)
                self.assertAlmostEqual(
                    float(data[key]), float(expected[key]), places=4
                )

    def test_demo_is_offline_capable(self):
        html = (ROOT / "demo" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("http://", html, "demo 不应依赖外链")
        self.assertNotIn("https://", html, "demo 不应依赖外链")

    def test_demo_shipments_match_pipeline_results(self):
        from yuexian.pipeline import run_dataset
        from yuexian.rules import load_dataset

        self.assertEqual(self._demo_data()["shipments"],
                         [flow["judgement"] for flow in run_dataset(load_dataset())])

    def test_hero_shipment_is_the_hold_case(self):
        data = self._demo_data()
        hero = next((s for s in data["shipments"] if s.get("demo")), None)
        self.assertIsNotNone(hero, "缺少主演示票")
        self.assertEqual(hero["headline"], "先别申报")
        self.assertEqual(hero["verdict"], "hold")

    def test_verify_submission_script_passes(self):
        import subprocess
        import sys
        import os

        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "verify_submission.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
