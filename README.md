# 校史馆社团议事档案工具

用 Python 3.11+ 标准库实现，完全离线。两个业务入口共用一个命令行程序：

- `roster`：从点名流水重建每案点名截点上的**盖章名册产品**（可投者、排除理由、所依据的具体流水），并区分“没资格”与“没举手”。
- `charter`：枚举所有合法修正案处理次序，逐案受理与表决，给出唯一终稿与签发记录；若次序不同导致终稿不同，则列出两份（或多份）不同终稿及各自合法议程与逐案理由。

辅助入口：`analyze`（跑遍 base 与全部 variants）、`member`（查某人某案当时是否有资格）、`reopen`（重开并校验签发记录）。

## 运行

```bash
# 全部样例：base 与 3 个 variants，并保存可重开的本地文件
python3 -m charter_tool analyze case.json --out out

# 只跑名册
python3 -m charter_tool roster case.json --case base

# 只跑章程（含签发记录）
python3 -m charter_tool charter case.json --case missing-order --out out

# 独立查某人某案资格
python3 -m charter_tool member case.json A M1 --case recusal --json

# 重开并校验一份已保存的签发记录
python3 -m charter_tool reopen out/base.signing.json
```

材料也可以从标准输入读入：把文件名换成 `-`。

## 规则落点

点名流水（`charter_tool/roll.py`）：

- 每条记录有稳定 `id` 与正整数 `rev`；同 `id` 取最高 `rev`。
- 最高版可为 `kind=cancel`，撤销整条原记录；撤销行只需 `id`/`rev`。
- 未撤销的 `kind` 为 `in`/`out`/`recuse`/`unrecuse`，后两者必须带 `motion`。
- 同 `id` 同 `rev` 但内容不同 → `conflicting_revision` 拒收。
- 生效记录按 `(t, seq)` 排序，该顺序键重复 → `duplicate_order_key` 拒收。
- 初始全员离席、无回避。到场/离席与逐案回避是两组独立布尔状态：离席只结束在场，回避保留；重新进场继承原回避。
- 回避只影响所指案号。

名册（`charter_tool/roster.py`）：在每个独立记录的 `(t, seq)` 截点（含该点）重放到该时刻，封存可投者、排除理由（`absent`/`recused`）及依据记录。选票三态 `yes`/`no`/`abstain`；**未录到举手**记为弃权（`explanation=no_hand_raised` 或 `ballot_not_recorded`），与**无资格**（`eligible=false`）严格区分。无资格者的选票不计入。

章程（`charter_tool/charter.py`）：

- 修正单仅在条款现文**整体等于**旧文时才受理（`text_mismatch` 记不受理）。
- 次序凭条 `before` 必须构成偏序；成环 → `order_cycle` 并给出环路径。枚举全部合法全序，每案在各全序中恰处理一次。
- 表决：点名可投人数 ≥ 法定人数，且赞成票**严格多于**有资格者实投反对票；弃权不进入赞反比较，全弃 / 无人赞成则不通过。
- 点名不合（`no_quorum`）或表决未过（`vote_not_passed`）保持条款。
- 所有合法次序给出**同一终稿**才 `signable`，并生成 `signing_record`（含终稿摘要、次序空间摘要、名册封印）。
- 有分歧时 `signable=false`，`contested.differing_finals` 给出每份不同终稿、一个合法议程与逐案理由/票据。

同终稿可对应不同受理过程：`outcomes[].distinct_processes` 与 `witnesses` 记录之。

## 样例结论

| 变体 | 结论 |
| --- | --- |
| `base` | 可签，终稿 `{"use":"合读"}` |
| `recusal`（补录 A 在 M1 前回避） | M1 可投 2 < 法定 3 → 不通过；M2 现文手稿不匹配 → 不受理；终稿仍是 `{"use":"自习"}`，可签 |
| `reverse-order`（凭条翻为 M2 先于 M1） | M2 不匹配 → 不受理；M1 通过 → `{"use":"报刊"}`，可签 |
| `missing-order`（无凭条） | 两种合法全序分别得 `合读` 与 `报刊`，**不可签**，交两份终稿 |

## 测试

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_roll.py` 覆盖修订/撤销/同版异文/顺序键/回避继承；`tests/test_roster.py` 覆盖截点含端点、缺报名册、弃权与无资格区分；`tests/test_charter.py` 覆盖成环、全序枚举、受理条件、法定人数、赞反严格多数、同终稿多过程、分歧两份终稿；`tests/test_sample.py` 端到端复核上述样例与签发文件重开。

## 文件

- `charter_tool/` — 引擎与 CLI
- `tools/reopen.py` — 独立的重开/校验脚本（也可用 `python -m charter_tool reopen`）
- `case.json` — 样例材料
- `tests/` — 单元与端到端测试
