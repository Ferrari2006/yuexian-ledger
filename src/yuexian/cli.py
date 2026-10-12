import argparse
import json
from pathlib import Path

from yuexian.documents import render_shipment
from yuexian.pipeline import run_ballast, run_batch
from yuexian.rules import load_dataset, score


def main() -> None:
    parser = argparse.ArgumentParser(description="先别申报")
    parser.add_argument("command", nargs="?", default="score", choices=["score", "docs", "batch", "ballast"])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    dataset = load_dataset()
    if args.command == "docs":
        _write_docs(dataset)
        return
    if args.command == "batch":
        copies = max(1, args.repeat)
        items = [item for item in dataset["shipments"] for _ in range(copies)]
        ran = run_batch(items, dataset["threshold_gross_weight"], workers=args.workers)
        counts = {"hold": 0, "review": 0, "send": 0}
        for item in ran:
            counts[item["judgement"]["verdict"]] += 1
        print(json.dumps({"count": len(ran), "workers": max(1, args.workers), "verdicts": counts}, ensure_ascii=False))
        return
    if args.command == "ballast":
        report = run_ballast(dataset, copies=max(1, args.repeat), workers=args.workers)
        print(json.dumps(report, ensure_ascii=False))
        return
    print(json.dumps(score(dataset), ensure_ascii=False, indent=2))


def _write_docs(dataset: dict) -> None:
    root = Path(__file__).resolve().parents[2] / "artifacts" / "documents"
    root.mkdir(parents=True, exist_ok=True)
    for shipment in dataset["shipments"]:
        folder = root / shipment["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in render_shipment(shipment).items():
            (folder / f"{name}.txt").write_text(text, encoding="utf-8")
    print(root)
