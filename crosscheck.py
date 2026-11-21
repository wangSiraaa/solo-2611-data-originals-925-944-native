#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交叉校验：用最朴素的独立暴力实现核对 chronicle.py 的全部结论。

不 import chronicle，避免共享实现偏差；仅读取同一批 case.json 与报告 JSON。
"""
import itertools
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def brute_family(fam):
    years = fam["years"]
    persons = list(years)
    sols = []
    for combo in itertools.product(*(years[p] for p in persons)):
        birth = dict(zip(persons, combo))
        picks = []
        ok = True
        for link in fam["links"]:
            lo, hi = link["age"]
            cand = [q for q in link["parents"]
                    if lo <= birth[link["child"]] - birth[q] <= hi]
            if not cand:
                ok = False
                break
            picks.append(cand)
        if not ok:
            continue
        if not picks:
            continue
        # 无环：候选家长是「或」，枚举全部择定，过滤掉成环的组合
        for choice in itertools.product(*picks):
            graph = {q: link["child"] for link, q in zip(fam["links"], choice)}
            color = {}

            def dfs(u):
                color[u] = 1
                v = graph.get(u)
                if v is not None:
                    if color.get(v) == 1 or (color.get(v, 0) == 0 and dfs(v)):
                        return True
                color[u] = 2
                return False

            if not any(color.get(u, 0) == 0 and dfs(u) for u in graph):
                sols.append({"birth": birth,
                             "parents": {link["id"]: q
                                         for link, q in zip(fam["links"], choice)}})
    return persons, sols


def brute_book(book, persons, fam_sols):
    """返回 (单叶边际年, 联合可行年对, 贯穿年序全集)。

    边际年只看单叶年龄条件跨家谱解的并集，与接缝是否允许贯穿无关；
    联合年对与贯穿年序才要求同时过接缝。
    """
    lo, hi = book["years"]
    year_list = list(range(lo, hi + 1))
    leaves, gaps = book["leaves"], book["gaps"]
    n = len(leaves)
    marg = {lf["id"]: set() for lf in leaves}
    pairs = {(i, j): set() for i in range(n) for j in range(i + 1, n)}
    full = []
    vectors = {tuple(s["birth"][p] for p in persons) for s in fam_sols}
    for vec in vectors:
        birth = dict(zip(persons, vec))
        leaf_years = []
        for lf in leaves:
            ys = [y for y in year_list
                  if all(m["age"][0] <= y - birth[m["person"]] <= m["age"][1]
                         for m in lf["mentions"])]
            leaf_years.append(ys)
        for i, lf in enumerate(leaves):  # 边际：不看接缝
            marg[lf["id"]].update(leaf_years[i])
        for seq in itertools.product(*leaf_years):
            if all(gaps[k][0] <= seq[k + 1] - seq[k] <= gaps[k][1]
                   for k in range(n - 1)):
                full.append((birth, seq))
                for (i, j) in pairs:
                    pairs[(i, j)].add((seq[i], seq[j]))
    return marg, pairs, full


def cli(payload_path, *args):
    out = subprocess.run([sys.executable, str(ROOT / "chronicle.py"), *args],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def check_case(case_path):
    raw = json.loads(Path(case_path).read_text(encoding="utf-8"))
    errs = []

    # --- 家谱原始与变更后 ---
    variants = [("原始", raw, None)]
    for idx, ch in enumerate(raw.get("changes", [])):
        if ch["path"].startswith("family."):
            mod = json.loads(json.dumps(raw))
            node = mod
            for part in ch["path"].split(".")[:-1]:
                node = node[part]
            node[ch["path"].split(".")[-1]] = ch["value"]
            variants.append((f"变更{idx}", mod, idx))

    for name, data, change_idx in variants:
        persons, bsols = brute_family(data["family"])
        cli_args = ["family", str(case_path), "--json"]
        if change_idx is not None:
            cli_args[1:1] = ["--change", str(change_idx)]
        got = cli(None, *cli_args)
        bvec = {tuple(s["birth"][p] for p in persons) for s in bsols}
        gvec = {tuple(s["birth"][p] for p in persons) for s in got["solutions"]}
        if bvec != gvec:
            errs.append(f"[{name}] 家谱解向量不一致：暴力 {sorted(bvec)} vs CLI {sorted(gvec)}")
        for p in persons:
            bf = {s["birth"][p] for s in bsols}
            gf = set(person_years(got, p))
            if bf != gf:
                errs.append(f"[{name}] {p} 可行年不一致")
        for a, b in itertools.combinations(persons, 2):
            bp = {(s["birth"][a], s["birth"][b]) for s in bsols}
            gp = {(s["birth"][a], s["birth"][b]) for s in got["solutions"]}
            if bp != gp:
                errs.append(f"[{name}] {a}/{b} 成对组合不一致")

    # --- 簿册原始与每条 book 变更 ---
    book_variants = [("原始", raw)]
    for idx, ch in enumerate(raw.get("changes", [])):
        if ch["path"].startswith("book."):
            mod = json.loads(json.dumps(raw))
            node = mod
            for part in ch["path"].split(".")[:-1]:
                node = node[part]
            node[ch["path"].split(".")[-1]] = ch["value"]
            book_variants.append((f"变更{idx}", (idx, mod)))

    persons, fam_sols = brute_family(raw["family"])
    for name, item in book_variants:
        data = raw if name == "原始" else item[1]
        if name == "原始":
            got = cli(None, "book", str(case_path), "--json")
        else:
            got = cli(None, "book", str(case_path), "--change", str(item[0]), "--json")
        bmarg, bpairs, bfull = brute_book(data["book"], persons, fam_sols)
        if not fam_sols:
            if got["status"] != "family_contradiction":
                errs.append(f"[{name}] 应判家谱矛盾")
            continue
        want_status = "ok" if bfull else "book_impossible"
        if got["status"] != want_status:
            errs.append(f"[{name}] 状态 {got['status']} != {want_status}")
        for lid, ys in bmarg.items():
            if set(got["marginals"].get(lid, [])) != ys:
                errs.append(f"[{name}] 叶 {lid} 边际年不一致")
        for (i, j), ys in bpairs.items():
            block = got["pairs"].get(f"{i}|{j}")
            if block is None:
                errs.append(f"[{name}] 缺少叶对 {i}/{j} 输出")
                continue
            if {tuple(v) for v in block["values"]} != ys:
                errs.append(f"[{name}] 叶对 {i}/{j} 联合年对不一致")
            # 每个可行年对必须附非空贯穿见证
            for v in block["values"]:
                w = block["witness"][f"{v[0]},{v[1]}"]
                if w is None or "leaf_years" not in w:
                    errs.append(f"[{name}] 年对 {v} 缺贯穿见证")
        if bfull:
            # 抽样核对每条见证确实满足全部约束
            for block in got["pairs"].values():
                for w in block["witness"].values():
                    seq = [w["leaf_years"][lf["id"]] for lf in data["book"]["leaves"]]
                    birth = w["birth"]
                    for k, lf in enumerate(data["book"]["leaves"]):
                        for m in lf["mentions"]:
                            if not (m["age"][0] <= seq[k] - birth[m["person"]] <= m["age"][1]):
                                errs.append(f"[{name}] 见证违反叶内年龄")
                    for k in range(len(seq) - 1):
                        g = data["book"]["gaps"][k]
                        if not (g[0] <= seq[k + 1] - seq[k] <= g[1]):
                            errs.append(f"[{name}] 见证违反接缝")
    return errs


def person_years(got, p):
    return sorted({s["birth"][p] for s in got["solutions"]})


if __name__ == "__main__":
    total = 0
    for case in sys.argv[1:]:
        errors = check_case(case)
        total += len(errors)
        print(f"{case}: {'全部一致 OK' if not errors else ''}")
        for e in errors:
            print("  FAIL:", e)
    raise SystemExit(1 if total else 0)
