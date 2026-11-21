# 音乐盒纸带：补孔制版 + 试奏进纸

两个可分别运行的业务入口，共用一个包 `musicbox/`：

| 入口 | 作用 |
| --- | --- |
| `platemaker.py` | 制版：按顺序贴补片（后贴生效、越界拒绝），输出补后的各轨、原轨、原孔左缘、拨齿清单 |
| `playtest.py` | 试奏：读制版清单，在回弹时间与换挡次数约束下，找使全部拨动都响且总用时最短的 fast/slow 进纸 |

只用 **Python 3.11 标准库**。`verify.py` 是无需信任求解器自述的复核脚本。

## 规则实现要点

- **纸带**：等长轨道，`0`=实纸、`1`=孔，列从 0 起。补片 `{track,start,bits}` 覆盖 `[start, start+len)`；后贴的覆盖先贴的；越界（`start<0` 或 `start+len>列数`）或目标轨不存在即拒绝。
- **读头与拨动**：`{track,tooth,offset}`，`offset>=0`。连续孔只在**左缘**拨一下；拨动落在 `左缘列 + offset` 刻位（下文称“刻”/tick）。
- **去重**：不同头在同一刻拨同一齿只响一次。`play` 是去重后的清单；`contributions` 保留每个来源（头、轨、列），`original_tracks` / `original_left_edges` 保留原带与原孔左缘。
- **K**：`K = 末列号 + 各读头错位量最大值`（`= (列数-1) + max(offset)`），即便末尾无音也走到 K。共 `K` 段行程。
- **进纸**：相邻刻之间取 `fast` 或 `slow` 个整数时间单位，`0 < fast < slow`，初挡任选。相邻两段用时**不同**才记一次换挡。`steps[t]` 是第 `t` 刻到第 `t+1` 刻的用时，恰好 `K` 段。
- **回弹**：同一齿两次**实际发音**间隔 `>= cooldown` 才可再响，**恰好相等可以**。求解器只在音真正能响时记账，绝不偷偷“跳过”漏音。
- **最短**：在所有满足 `换挡次数 <= max_changes` 且每拨都响的进纸里，取总用时（`K` 段之和）最小者；并列任给一种（确定性地取字典序最小的起点/序列）。

## 样例运行

```bash
# 制版：单轨 10101，单头在 C 齿、错位 0
python3.11 platemaker.py --tracks T=10101 --heads T:C:0

# 制版：给第 1 列补孔（后贴生效）
python3.11 platemaker.py --tracks T=10101 --heads T:C:0 --patch T:1:1

# 试奏：同一带，回弹 3，fast=1 slow=2，最多 1 次换挡
python3.11 playtest.py --tracks T=10101 --heads T:C:0 \
    --cooldown C=3 --fast 1 --slow 2 --max-changes 1

# 跑完整基准（基准 + 每个 change 各从基准派生一次）
python3.11 playtest.py --case case.json

# 制版产物直接喂给试奏（读 stdin）
python3.11 platemaker.py --tracks T=10101 --heads T:C:0 \
  | python3.11 playtest.py --play-file - --cooldown C=3 --fast 1 --slow 2 --max-changes 1
```

两个入口都输出 JSON；`playtest` 无解时 `solve.solved=false`、`reason` 说明原因，进程返回 1。

## 基准结果（`case.json`）

| 变体 | 补后轨 | 拨齿刻位 | 最短总用时 | 一种进纸（steps） |
| --- | --- | --- | --- | --- |
| baseline | `10101` | 0, 2, 4 | **7** | `[1,2,2,2]`（1 次换挡） |
| change1 `plate.patches`：第 1 列补 1 | `11101` | 0, 4（前两孔连成长孔） | **4** | `[1,1,1,1]`（0 次换挡） |
| change2 `bench.max_changes`=2：保持原带 | `10101` | 0, 2, 4 | **6** | `[1,2,2,1]`（2 次换挡） |

复核：baseline 间隔 `0→3→7`，后两段恰为 3；patch 后 `0→4`，4≥3；改挡后 `0→3→6`，间隔均 3。

## 两个额外核对样例（`demos/`）

```bash
# 双头同齿同时拨：两轨同图案、两头都指 C 齿，同时刻只响一次
python3.11 playtest.py --plate-file demos/two_heads_same_tooth.json
#   -> solved=true, total_time=7；6 个来源拨动收敛为 3 次发音

# 回弹太慢的齿梳：cooldown=9，但 3 列带 K=2、最大可达间隔 2*slow=4 < 9
python3.11 playtest.py --plate-file demos/slow_comb_unsolvable.json
#   -> solved=false，reason 指出 C@0/C@2 需要 9，任何进纸都不够
```

## 复跑检验

```bash
python3.11 verify.py          # 完整（默认 600 组随机对拍）
python3.11 verify.py --quick  # 200 组
```

`verify.py` 独立复核：

1. 基准三项（7 / 4 / 6）与拨齿刻位；
2. 补片语义（后贴生效、原轨保留、越界/未知轨拒绝）；
3. 左缘→刻位映射、K、同刻同齿去重、不同齿并存；
4. 回弹“恰好相等可以 / 少一单位即漏”、换挡计数与上限；
5. 与**穷举所有 fast/slow 进纸**的结果对拍随机小盘，并回放求解器给出的进纸；
6. 两个额外样例（双头同齿、慢回弹无解）及其文件版。

## 文件结构

```
platemaker.py            制版入口
playtest.py              试奏入口
verify.py                可复跑检验
case.json                题给基准
musicbox/
  model.py               纸带/补片/左缘/去重/K + bench 校验 + 进纸模拟
  solver.py              精确动态规划求最短进纸（状态含各齿“距上次发音时长”）
  case.py                读 case.json、dot-path 替换、派生变体、期望值核对
  cli.py                 两个入口共用的命令/输出逻辑
demos/
  two_heads_same_tooth.json
  slow_comb_unsolvable.json
```

## 求解器为何是精确的

状态取 `(刻, 已用换挡数, 上一段用时, 各齿距上次发音的时长)`。回弹判定只依赖“距上次发音的时长”，因此对相同状态保留累计用时最小者即严格占优；时长按 `min(cooldown, K*slow)` 截断不改变可判性。逐刻推进即得全局最短。规模上界 12 列、3 头、错位 ≤ 2，实测数千次满规模求解均在毫秒级。
