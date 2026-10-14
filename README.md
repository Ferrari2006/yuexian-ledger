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

做：中国侧、申报接受前的毛重偏差、柜号封条、四国口径混填，以及「抽取看错不算改写」。文本先按类型调度，再去掉页眉和水印。缺栏位、不合规或未接入的文件只让这一票变成「资料待核验」。

不做：在本项目里解析目的国证书、PDF、HS 编码，也不做货运追踪、贸易问答、多级库存、数据中台。`src/yuexian/store.py` 只放以后接库的表结构，演示和判定都不调用它。

多票复跑：`python -m yuexian batch --repeat 20`。压舱并核对回退：`python -m yuexian ballast --repeat 40`。

本地文本单证包检查：`python -m yuexian check --input data/text_bundles/hold.json --output report.json`。可提供自己的装箱单、提单和舱单标签文本；输出保留字段原文与行号，并检查混票、重复字段与跨单证国家冲突。格式、范围和验证记录见[文本单证接入与证据记录](docs/文本单证接入与证据记录.md)。

赛题一的[平台运营方案](docs/赛题一-运营方案.md)覆盖 STP、4P、图文获客与社群承接、用户激活与持续使用、统一实测执行和数据复盘，与检查台分开提交；配套[执行材料与记录模板](docs/赛题一-运营执行材料.md)。目前方案和模板已准备，渠道合作、平台能力核验及实测结果仍待落实。文档提交步骤见[GitHub提交操作说明](docs/GitHub提交操作说明.md)。

数据流见 `docs/数据流.md`，判定见 `docs/算法.md`，扩展见 `docs/扩展.md`，提交见 `docs/提交清单.md`。

## 五人分工

见 `docs/OWNERS.md`。角色先占坑，GitHub 用户名由组员填上后再改 CODEOWNERS。
