"""把规则结果写进可离线打开的申报前检查台。"""

from __future__ import annotations

import json
from pathlib import Path

from yuexian.pipeline import run_dataset, run_shipment
from yuexian.rules import (
    field_timeline,
    load_dataset,
    resolve_shipment,
    resolution_options,
    score,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "demo" / "index.html"

STATION = {
    "booking": "订舱",
    "packing": "装箱单",
    "bl": "提单",
    "manifest": "舱单",
    "declaration": "报关草稿",
}

ACTION_LABELS = {
    "gross_weight:packing": "以装箱单毛重为准",
    "gross_weight:bl": "以提单毛重为准",
    "container_no:bl": "以提单柜号为准",
    "container_no:manifest": "以舱单柜号为准",
    "seal_no:bl": "以提单封条号为准",
    "seal_no:manifest": "以舱单封条号为准",
    "countries:split": "拆分四国字段",
}


def main() -> None:
    dataset = load_dataset()
    payload = score(dataset)
    flows = run_dataset(dataset)
    payload["shipments"] = [item["judgement"] for item in flows]
    threshold = dataset["threshold_gross_weight"]
    states = {
        shipment["id"]: _resolution_states(shipment, threshold)
        for shipment in dataset["shipments"]
    }
    page_flows = {
        item["id"]: {key: item[key] for key in ("documents", "trace", "explanation")}
        for item in flows
    }
    html = _page(payload, page_flows, states)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(OUT)


def _resolution_states(shipment: dict, threshold: float) -> dict[str, dict]:
    """预先计算每一种人工确认路径，前端不复制任何判定规则。"""
    states: dict[str, dict] = {}
    pending: list[tuple[dict, tuple[str, ...]]] = [(shipment, ())]
    while pending:
        candidate, tokens = pending.pop(0)
        key = "|".join(sorted(tokens))
        if key in states:
            continue
        flow = run_shipment(candidate, threshold)
        judged = flow["judgement"]
        choices = resolution_options(judged)
        states[key] = {
            "judgement": judged,
            "documents": flow["documents"],
            "trace": flow["trace"],
            "explanation": flow["explanation"],
            "choices": choices,
            "applied": [ACTION_LABELS[token] for token in sorted(tokens)],
            "timelines": {
                "gross_weight": field_timeline(candidate, "gross_weight_kg"),
                "container_no": field_timeline(candidate, "container_no"),
                "seal_no": field_timeline(candidate, "seal_no"),
            },
            "countries": candidate.get("countries", {}),
        }
        for choice in choices:
            pending.append((resolve_shipment(candidate, choice["token"]), (*tokens, choice["token"])))
    return states


def _page(payload: dict, flows: dict, states: dict[str, dict]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    flow_data = json.dumps(flows, ensure_ascii=False)
    state_data = json.dumps(states, ensure_ascii=False)
    stations = json.dumps(STATION, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>先别申报</title>
<style>
  body {{ margin: 0; font-family: "Microsoft YaHei", sans-serif; background: #f6f3ee; color: #1a1a1a; }}
  header {{ padding: 20px 28px 0; }}
  h1 {{ margin: 0; font-size: 28px; }}
  h2 {{ margin: 20px 0 8px; font-size: 20px; }}
  .sub {{ color: #5c6b73; margin-top: 6px; }}
  main {{ display: grid; grid-template-columns: 280px 1fr; gap: 16px; padding: 16px 28px 28px; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ background: #fff; border: 1px solid #d9d3cb; padding: 12px; margin-bottom: 8px; cursor: pointer; }}
  li.hold {{ border-color: #b42318; }}
  li.review {{ border-color: #a15c00; }}
  li.active {{ box-shadow: inset 4px 0 #1b3a4b; }}
  .panel {{ background: #fff; border: 1px solid #d9d3cb; padding: 20px; min-height: 420px; }}
  .banner {{ background: #b42318; color: #fff; padding: 14px 16px; font-size: 28px; font-weight: 700; }}
  .banner.ok {{ background: #1f6b4a; }}
  .banner.review {{ background: #a15c00; }}
  .reason {{ margin: 12px 0 0; padding: 10px 12px; background: #f6f3ee; border-left: 4px solid #1b3a4b; }}
  .docs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }}
  .paper {{ border: 1px solid #1b3a4b; background: #fffdf8; padding: 14px 16px; font-family: "SimSun", "Microsoft YaHei", serif; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }}
  .paper h3 {{ margin: 0 0 8px; font-size: 16px; text-align: center; }}
  .hit {{ background: #ffd6d1; }}
  .evidence {{ border-left: 4px solid #1b3a4b; background: #f1f5f6; padding: 12px 14px; margin-top: 14px; }}
  .timeline {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 8px; }}
  .point {{ border: 1px solid #c7d1d6; background: #fff; padding: 9px; min-height: 54px; }}
  .point.changed {{ border-color: #b42318; background: #fff4f2; }}
  .point strong {{ display: block; font-size: 13px; }}
  .point span {{ color: #5c6b73; font-size: 12px; }}
  .choice {{ margin: 8px 8px 0 0; background: #1b3a4b; color: #fff; border: 0; padding: 9px 12px; font-size: 14px; cursor: pointer; }}
  .resolved {{ border: 1px solid #88b39d; background: #eef8f1; padding: 10px 12px; margin-top: 14px; }}
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0 28px 20px; }}
  .stat {{ background: #fff; border: 1px solid #d9d3cb; padding: 14px; }}
  .stat strong {{ display: block; font-size: 26px; color: #1b3a4b; }}
  footer {{ padding: 0 28px 24px; color: #5c6b73; }}
</style>
</head>
<body>
<header>
  <h1>待申报</h1>
  <p class="sub">合成样例。规则判定。抽取看错的数字不参与结论。</p>
</header>
<main>
  <ul id="list"></ul>
  <section class="panel" id="panel"></section>
</main>
<section class="stats" id="stats"></section>
<footer id="foot"></footer>
<script>
const DATA = {data};
const FLOWS = {flow_data};
const STATES = {state_data};
const STATION = {stations};
const list = document.getElementById("list");
const panel = document.getElementById("panel");
let currentId = "";
let currentKey = "";

function escapeHtml(text) {{
  return String(text || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;");
}}

function paper(title, text, hit) {{
  const marked = escapeHtml(text);
  const html = hit ? marked.replace(hit, `<span class="hit">${{hit}}</span>`) : marked;
  return `<div class="paper"><h3>${{title}}</h3><div>${{html}}</div></div>`;
}}

function timeline(points) {{
  return `<div class="timeline">${{points.map(point => `
    <div class="point ${{point.changed ? "changed" : ""}}">
      <strong>${{point.label}}</strong>
      <span>${{point.value === null ? "未记录" : point.value}}</span>
      ${{point.changed ? "<span>首次可观察差异</span>" : ""}}
    </div>`).join("")}}</div>`;
}}

function evidence(state, judged) {{
  let html = "";
  const weight = judged.blocks.find(block => block.kind === "gross_weight");
  const device = judged.blocks.find(block => block.kind === "container_no" || block.kind === "seal_no");
  const countries = judged.blocks.find(block => block.kind === "countries");
  if (weight) {{
    html += `<div class="evidence"><strong>毛重版本轨迹</strong>${{timeline(state.timelines.gross_weight)}}<p>红框表示相对上一站的首次可观察差异。当前装箱单与提单相差 ${{Math.round(weight.gap * 1000) / 10}}%。</p></div>`;
  }}
  if (device) {{
    html += `<div class="evidence"><strong>${{device.title}}版本轨迹</strong>${{timeline(state.timelines[device.kind])}}<p>${{device.if_send}}。</p></div>`;
  }}
  if (countries) {{
    const c = state.countries;
    html += `<div class="evidence"><strong>国家字段证据</strong><p>国家栏：${{c.collapsed_value || "已拆分"}}；贸易国：${{c.trade || "未记录"}}；启运国：${{c.departure || "未记录"}}；原产国：${{c.origin || "未记录"}}；目的国：${{c.destination || "未记录"}}。</p></div>`;
  }}
  return html;
}}

function render(item, key = "") {{
  currentId = item.id;
  currentKey = STATES[currentId][key] ? key : "";
  const state = STATES[currentId][currentKey];
  const judged = state.judgement;
  const weight = judged.blocks.find(block => block.kind === "gross_weight");
  const packingHit = weight ? String(weight.packing_kg) : "";
  const blHit = weight ? String(weight.bl_kg) : "";
  const bannerClass = judged.verdict === "send" ? "ok" : (judged.verdict === "review" ? "review" : "");
  const steps = (state.trace || []).map(step => step.stage).join(" → ");
  const prep = (state.trace || []).find(step => step.stage === "preprocess") || {{ dropped_noise: 0, fallbacks: [] }};
  const dispatch = (state.trace || []).find(step => step.stage === "dispatch");
  const route = dispatch ? `${{dispatch.rule}} → ${{dispatch.handler}}` : "text/form";
  const backs = (prep.fallbacks || []).map(item => `${{item.document}} ${{item.fallback}}`).join("、");
  let body = `<div class="banner ${{bannerClass}}">${{judged.headline}}</div>`;
  body += `<p class="reason">${{state.explanation}}</p>`;
  body += `<p>${{item.id}} · ${{item.title}}</p>`;
  body += `<p class="sub">数据流：${{steps}}</p>`;
  body += `<p class="sub">调度 ${{route}}。预处理去掉 ${{prep.dropped_noise}} 行噪声。${{backs ? "回退 " + backs + "。" : ""}}结论只来自规则。</p>`;
  body += `<div class="docs">${{paper("装箱单", state.documents.packing, packingHit)}}${{paper("提单", state.documents.bl, blHit)}}</div>`;
  const extras = ["booking", "manifest", "declaration"].filter(name => state.documents[name]);
  if (extras.length) {{
    body += `<details><summary>查看历史与舱单依据</summary>${{extras.map(name => paper(STATION[name], state.documents[name], "")).join("")}}</details>`;
  }}
  body += evidence(state, judged);
  if (state.applied.length) {{
    body += `<div class="resolved"><strong>已完成的整改：</strong>${{state.applied.join("；")}}。系统已按整改后的副本重新判定。</div>`;
  }}
  if (judged.verdict === "hold" && state.choices.length) {{
    body += `<h2>确认依据并复检</h2><p>选择一份单据作为本次整改依据。原始样例不会被改写。</p>`;
    body += state.choices.map(choice => `<button class="choice" data-token="${{choice.token}}">${{choice.label}}</button>`).join("");
  }} else if (judged.verdict === "send") {{
    body += `<div class="resolved"><strong>复检通过。</strong>当前三单的已覆盖字段不再触发阻塞规则，可以进入申报准备。</div>`;
  }}
  panel.innerHTML = body;
  panel.querySelectorAll("button[data-token]").forEach(button => {{
    button.onclick = () => {{
      const tokens = currentKey ? currentKey.split("|") : [];
      tokens.push(button.dataset.token);
      render(item, tokens.sort().join("|"));
    }};
  }});
  document.querySelectorAll("#list li").forEach(li => li.classList.toggle("active", li.dataset.id === currentId));
}}

DATA.shipments.forEach(item => {{
  const li = document.createElement("li");
  li.className = item.verdict === "send" ? "" : item.verdict;
  li.dataset.id = item.id;
  li.textContent = `${{item.headline}} · ${{item.id}}`;
  li.onclick = () => render(item);
  list.appendChild(li);
}});
const demo = DATA.shipments.find(item => item.demo) || DATA.shipments[0];
render(demo);
const ratio = Math.round(DATA.birth_station_ratio * 100);
document.getElementById("stats").innerHTML = `
  <div class="stat"><strong>${{DATA.birth_station_hit}}/${{DATA.birth_station_total}}</strong>站点改写落在装箱或舱单（${{ratio}}%）</div>
  <div class="stat"><strong>${{DATA.country_mix_count}}</strong>四国口径混填判错的票数</div>
  <div class="stat"><strong>${{DATA.weight_hold_count}}</strong>毛重越过约 3% 的票数</div>`;
document.getElementById("foot").textContent = DATA.threshold_note;
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
