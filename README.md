# 先别申报

华东师大 AI 智能体校园黑客松 · 赛题二方向三的可运行检查台。

单证员在把申报发给海关之前，打开一票货，第一眼看到能不能发。单证文本先被抽成字段，再由规则判定。解释只复述判定。设置 `DASHSCOPE_API_KEY` 时，千问会再抽一版对照，不能改「先别申报」。

## 现在就能看

用浏览器直接打开 `demo/index.html`。列表里红色的一票是主演示，点进去是「先别申报」、两处毛重和要改的栏。页脚三个数由规则对全部样例复算，不是手填的。

交稿说明可直接粘贴 `docs/作品说明-DataClawHub.md`。三分钟讲稿在 `docs/路演稿.md`。导出合成单证：`python -m yuexian docs`。

```powershell
python -m pip install -e .
python -m unittest discover -s tests -t . -v
python -m yuexian.build_demo
```

`-t .` 让`tests` 作为包导入，其中的路径引导会把 `src/` 加入 `sys.path`；
但重建演示页或导出单证需要先安装本包。若需要 `pytest`，可改用
`pip install -e ".[dev]"`。

## 最终版范围

做：中国侧、申报接受前的毛重偏差、柜号封条、四国口径混填，以及「抽取看错不算改写」。

不做：目的国证书、货运追踪、贸易问答、多级库存、数据中台。

赛题一运营方案在 `docs/赛题一-运营方案.md`，与本仓库的检查台分开写。

数据流见 `docs/数据流.md`，判定见 `docs/算法.md`，扩展见 `docs/扩展.md`，提交见 `docs/提交清单.md`。

## 五人分工

见 `docs/OWNERS.md`。角色先占坑，GitHub 用户名由组员填上后再改 CODEOWNERS。
