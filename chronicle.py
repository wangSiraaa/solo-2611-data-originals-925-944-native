#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""家谱校年与无年份工坊簿册断代。

只用 Python 3.11 标准库。年份均为小整数，岁数直接取两个年份之差，
全程不涉及公历。

两部分业务：
  家谱端：对每条亲缘记载择一位家长、为每个人择一个出生年，
          满足全部生育年龄闭区间且亲缘方向无环；支持单人 / 双人
          可行年查询，每个结论都附一套完整见证。
  簿册端：在同一套可共存家谱解之上，为装订固定的各叶定书写年，
          满足叶内年龄闭区间与相邻叶接缝闭区间；给出每叶全部真正
          可行年份、任意两叶联合可行年对，结论均附贯穿整册的见证，
          并区分「家谱本身矛盾」与「家谱有解但此册编不成」。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

# ----------------------------------------------------------------------
# 输入装载、校验、变更应用
# ----------------------------------------------------------------------


class InputError(ValueError):
    """原始名册 / 簿册数据不合法。"""


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise InputError(msg)


def load_json(path: str) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"无法读取 {path}：{exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} 不是合法 JSON：{exc}") from exc
    _check(isinstance(data, dict), "顶层结构须为 JSON 对象")
    _check("family" in data and "book" in data, "case 须同时含 family 与 book")
    return data


def validate_family(fam: dict) -> tuple[dict, list]:
    years = fam.get("years")
    _check(isinstance(years, dict) and years, "family.years 须为非空对象")
    for person, ys in years.items():
        _check(isinstance(ys, list) and ys, f"{person} 的候选出生年须为非空列表")
        _check(all(isinstance(y, int) for y in ys), f"{person} 的候选年均须为整数")
        _check(len(ys) == len(set(ys)), f"{person} 的候选年须离散、互不相同")
        years[person] = sorted(ys)

    links = fam.get("links", [])
    _check(isinstance(links, list), "family.links 须为列表")
    seen_ids = set()
    for k, link in enumerate(links):
        lid = str(link.get("id", f"link{k}"))
        _check(lid not in seen_ids, f"亲缘记载 id 重复：{lid}")
        seen_ids.add(lid)
        link["id"] = lid
        parents = link.get("parents")
        _check(isinstance(parents, list) and parents, f"记载 {lid} 须至少一位候选家长")
        _check(len(parents) == len(set(parents)), f"记载 {lid} 候选家长重复")
        for q in parents:
            _check(q in years, f"记载 {lid} 的候选家长 {q} 不在名册中")
        child = link.get("child")
        _check(child in years, f"记载 {lid} 的孩子 {child} 不在名册中")
        age = link.get("age")
        _check(isinstance(age, list) and len(age) == 2, f"记载 {lid} 的 age 须为 [下限,上限]")
        lo, hi = age
        _check(isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi,
               f"记载 {lid} 的生育年龄闭区间非法")
    return years, links


def validate_book(book: dict, persons: list[str]) -> tuple[list, list, list]:
    span = book.get("years")
    _check(isinstance(span, list) and len(span) == 2, "book.years 须为 [下限,上限]")
    lo, hi = span
    _check(isinstance(lo, int) and isinstance(hi, int) and lo <= hi, "book.years 闭区间非法")
    year_list = list(range(lo, hi + 1))

    leaves = book.get("leaves")
    _check(isinstance(leaves, list) and leaves, "book.leaves 须为非空列表")
    for i, leaf in enumerate(leaves):
        lid = str(leaf.get("id", f"leaf{i}"))
        leaf["id"] = lid
        mentions = leaf.get("mentions")
        _check(isinstance(mentions, list) and mentions, f"叶 {lid} 须至少记载一人")
        for m in mentions:
            _check(m.get("person") in persons, f"叶 {lid} 记载的 {m.get('person')} 不在家谱名册中")
            age = m.get("age")
            _check(isinstance(age, list) and len(age) == 2, f"叶 {lid} 的 age 须为 [下限,上限]")
            alo, ahi = age
            _check(isinstance(alo, int) and isinstance(ahi, int) and 0 <= alo <= ahi,
                   f"叶 {lid} 上 {m['person']} 的年龄闭区间非法")

    gaps = book.get("gaps")
    _check(isinstance(gaps, list), "book.gaps 须为列表")
    _check(len(gaps) == len(leaves) - 1,
           f"接缝数 {len(gaps)} 须等于叶数减一 {len(leaves) - 1}")
    for i, gap in enumerate(gaps):
        _check(isinstance(gap, list) and len(gap) == 2, f"接缝 {i} 须为 [下限,上限]")
        glo, ghi = gap
        _check(isinstance(glo, int) and isinstance(ghi, int) and 0 <= glo <= ghi,
               f"接缝 {i} 为非负闭区间，给定值非法")
    return year_list, leaves, gaps


def apply_change(raw: dict, spec: dict) -> dict:
    """按点路径（如 family.years.甲）把 value 整体替换进原始输入的深拷贝。"""
    _check("path" in spec and "value" in spec, "change 须含 path 与 value")
    data = copy.deepcopy(raw)
    parts = spec["path"].split(".")
    node = data
    for part in parts[:-1]:
        _check(part in node, f"变更路径不存在：{spec['path']}")
        node = node[part]
    _check(parts[-1] in node, f"变更路径不存在：{spec['path']}")
    node[parts[-1]] = copy.deepcopy(spec["value"])
    return data


# ----------------------------------------------------------------------
# 家谱端：枚举全部完整解释
# ----------------------------------------------------------------------


def _graph_has_cycle(edges: list[tuple[str, str]]) -> bool:
    """标准三色 DFS：给定具体的 (家长, 孩子) 有向边集合是否成环（含自指）。"""
    graph: dict[str, list[str]] = {}
    for parent, child in edges:
        graph.setdefault(parent, []).append(child)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in graph.get(u, ()):
            cv = color.get(v, WHITE)
            if cv == GRAY:
                return True
            if cv == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color.get(u, WHITE) == WHITE and dfs(u) for u in graph)


def _acyclic_choice_exists(links: list, age_ok_parents: list[list[str]]) -> bool:
    """在每条记载各自的可行候选家长中，是否存在一组使家长->孩子图无环。

    候选家长是「或」关系：任意单条记载的环不能宣判无解，必须跨全部记载
    联合判断。记载至多 3 条、每条至多 2 位候选，枚举全部择定组合并对每个
    具体有向图做三色环检测，组合数有界且语义直白。
    """
    option_sets = [[(link["child"], q) for q in parents]
                   for link, parents in zip(links, age_ok_parents)]

    def enumerate_choices(k: int, chosen: list[tuple[str, str]]) -> bool:
        if k == len(links):
            return not _graph_has_cycle(chosen)
        return any(enumerate_choices(k + 1, chosen + [edge])
                   for edge in option_sets[k])

    return enumerate_choices(0, [])


def solve_family(years: dict, links: list) -> tuple[list[str], list[dict]]:
    """枚举全部完整解释。

    解结构：{"birth": {人: 出生年}, "parents": {记载id: 选中的家长}}。
    同一人在所有记载中共享同一出生年；每条记载独立择家长。
    """
    persons = list(years)
    solutions: list[dict] = []
    assignment: dict[str, int] = {}

    def solve_links(k: int, age_ok: list[list[str]]) -> None:
        if k == len(links):
            if _acyclic_choice_exists(links, age_ok):
                # 无环选择可能不止一组，逐组落盘为不同的完整解释。
                def emit(t: int, picks: list[str]) -> None:
                    if t == len(links):
                        solutions.append({
                            "birth": dict(assignment),
                            "parents": {links[j]["id"]: picks[j]
                                        for j in range(len(links))},
                        })
                        return
                    for q in age_ok[t]:
                        emit(t + 1, picks + [q])
                emit(0, [])
            return
        link = links[k]
        lo, hi = link["age"]
        child_year = assignment[link["child"]]
        feasible = [q for q in link["parents"]  # 各条记载独立择家长
                    if lo <= child_year - assignment[q] <= hi]
        if feasible:
            solve_links(k + 1, age_ok + [feasible])

    def gen_person(i: int) -> None:
        if i == len(persons):
            solve_links(0, [])
            return
        person = persons[i]
        for y in years[person]:
            assignment[person] = y
            gen_person(i + 1)

    gen_person(0)
    return persons, solutions


def person_feasible(solutions: list[dict], person: str) -> dict[int, dict]:
    """某人的可行出生年，每个年附一套完整见证。"""
    out: dict[int, dict] = {}
    for s in solutions:
        y = s["birth"][person]
        if y not in out:
            out[y] = s
    return dict(sorted(out.items()))


def pair_feasible(solutions: list[dict], p1: str, p2: str) -> dict[tuple, dict]:
    """两人共同可行的（出生年甲, 出生年乙）组合及见证。"""
    out: dict[tuple, dict] = {}
    for s in solutions:
        key = (s["birth"][p1], s["birth"][p2])
        if key not in out:
            out[key] = s
    return dict(sorted(out.items()))


def diagnose_family(years: dict, links: list) -> list[dict]:
    """家谱无解时给出逐条出生年组合下的失败原因。"""
    persons = list(years)
    assignment: dict[str, int] = {}
    findings: list[dict] = []

    def inspect() -> None:
        age_ok: list[list[str]] = []
        for link in links:
            lo, hi = link["age"]
            cy = assignment[link["child"]]
            feasible = [q for q in link["parents"]
                        if lo <= cy - assignment[q] <= hi]
            if not feasible:
                findings.append({
                    "type": "age",
                    "link": link["id"],
                    "child": link["child"],
                    "assignment": dict(assignment),
                    "detail": "所有候选家长在该出生年组合下的生育年龄都不在闭区间 "
                              f"[{lo}, {hi}] 内",
                })
                return
            age_ok.append(feasible)
        if not _acyclic_choice_exists(links, age_ok):
            findings.append({
                "type": "cycle",
                "link": None,
                "child": None,
                "assignment": dict(assignment),
                "detail": "年龄条件虽可满足，但跨全部记载的任何家长择定都使家长->孩子方向成环",
            })

    def gen(i: int) -> None:
        if i == len(persons):
            inspect()
            return
        person = persons[i]
        for y in years[person]:
            assignment[person] = y
            gen(i + 1)

    gen(0)
    return findings


# ----------------------------------------------------------------------
# 簿册端：在可共存家谱解上为各叶断代
# ----------------------------------------------------------------------


def _leaf_ok_years(leaf: dict, year_list: list[int], birth: dict) -> list[int]:
    mentions = leaf["mentions"]
    out = []
    for y in year_list:  # 同一叶上所有人共用同一书写年
        if all(m["age"][0] <= y - birth[m["person"]] <= m["age"][1]
               for m in mentions):
            out.append(y)
    return out


def solve_book(book: dict, persons: list[str], fam_solutions: list[dict]) -> dict:
    """簿册断代。fam_solutions 为空时判定为家谱本身矛盾。"""
    year_list, leaves, gaps = validate_book(book, persons)
    n = len(leaves)
    leaf_ids = [lf["id"] for lf in leaves]
    base = {"range": [year_list[0], year_list[-1]], "leaf_ids": leaf_ids, "gaps": gaps}

    if not fam_solutions:
        return {**base, "status": "family_contradiction",
                "diagnosis": ["家谱本身无完整解释，簿册无从编起"],
                "marginals": {}, "pairs": {}}

    # 家谱解按出生年向量去重：簿册只关心出生年与整套关系是否可共存，
    # 同一出生年向量保留一份含家长择定的见证即可。
    dedup: dict[tuple, dict] = {}
    for s in fam_solutions:
        key = tuple(s["birth"][p] for p in persons)
        dedup.setdefault(key, s)
    fam_list = list(dedup.values())

    # 先廉价算出每叶目标候选年与两两目标年对。非相邻叶只要求来自同一套家谱；
    # 相邻叶还须满足该接缝的年差闭区间。该目标集仅用于判断见证是否集齐。
    target_marg = [set() for _ in range(n)]
    target_pair: dict[tuple, set] = {(i, j): set()
                                     for i in range(n) for j in range(i + 1, n)}
    per_solution_leaves: list[list[set]] = []
    for s in fam_list:
        per_leaf = [set(_leaf_ok_years(lf, year_list, s["birth"])) for lf in leaves]
        per_solution_leaves.append(per_leaf)
        for i in range(n):
            target_marg[i] |= per_leaf[i]
        for (i, j), bucket in target_pair.items():
            for y in per_leaf[i]:
                for z in per_leaf[j]:
                    if j == i + 1:
                        glo, ghi = gaps[i]
                        if not (glo <= z - y <= ghi):
                            continue
                    bucket.add((y, z))

    marg_witness: list[dict] = [dict() for _ in range(n)]
    # 联合可行 = 至少出现在一条贯穿整册年序中的年对，故只保留有见证的对。
    pair_witness: dict[tuple, dict] = {k: dict() for k in target_pair}

    def all_witnesses_filled() -> bool:
        for i in range(n):
            if set(marg_witness[i]) != target_marg[i]:
                return False
        for key, bucket in target_pair.items():
            if set(pair_witness[key]) != bucket:
                return False
        return True

    # 对每套可共存家谱做接缝剪枝 DFS，收集贯穿整册的见证；边际集齐即停。
    stop = False
    for s, per_leaf in zip(fam_list, per_solution_leaves):
        if stop:
            break
        seq: list[int] = []

        def dfs(idx: int) -> None:
            nonlocal stop
            if stop:
                return
            if idx == n:
                witness = {"birth": s["birth"], "parents": s["parents"],
                           "leaf_years": dict(zip(leaf_ids, seq))}
                for i, y in enumerate(seq):
                    marg_witness[i].setdefault(y, witness)
                for (i, j), bucket in pair_witness.items():
                    bucket.setdefault((seq[i], seq[j]), witness)
                if all_witnesses_filled():
                    stop = True
                return
            for y in sorted(per_leaf[idx]):
                if idx == 0:
                    ok = True
                else:
                    glo, ghi = gaps[idx - 1]
                    ok = glo <= y - seq[-1] <= ghi
                if ok:
                    seq.append(y)
                    dfs(idx + 1)
                    seq.pop()

        dfs(0)

    marginals = {leaf_ids[i]: sorted(target_marg[i]) for i in range(n)}
    pairs_out = {}
    for (i, j) in sorted(target_pair):
        bucket = pair_witness[(i, j)]
        pairs_out[f"{i}|{j}"] = {
            "leaves": [leaf_ids[i], leaf_ids[j]],
            "values": [[y, z] for (y, z) in sorted(bucket)],
            "witness": {f"{y},{z}": bucket[(y, z)] for (y, z) in sorted(bucket)},
        }

    status = "ok" if all(target_marg[i] and marg_witness[i] for i in range(n)) \
        else "book_impossible"
    diagnosis = []
    if status == "book_impossible":
        for i, lf in enumerate(leaves):
            if not target_marg[i]:
                diagnosis.append(
                    f"叶 {lf['id']}：任取一套可共存家谱出生年，其年龄闭区间都无法在馆方年份范围"
                    f" [{year_list[0]}, {year_list[-1]}] 内落年")
        for i in range(n - 1):
            glo, ghi = gaps[i]
            if not target_pair[(i, i + 1)]:
                diagnosis.append(
                    f"接缝 {leaves[i]['id']} -> {leaves[i + 1]['id']}（要求年差 [{glo}, {ghi}]）："
                    f"两叶各自有候选年 {sorted(target_marg[i])} / {sorted(target_marg[i + 1])}，"
                    "但没有任何年对满足该接缝")
        if not diagnosis:
            diagnosis.append("每条接缝单独看都有年对可过，但不存在同时满足全部接缝的贯穿年序")

    return {**base, "status": status, "diagnosis": diagnosis,
            "marginals": marginals,
            "marginal_witness": {leaf_ids[i]: {str(y): marg_witness[i].get(y)
                                               for y in sorted(target_marg[i])}
                                 for i in range(n)},
            "pairs": pairs_out}


# ----------------------------------------------------------------------
# 中文报告
# ----------------------------------------------------------------------


def _fmt_witness(w: dict) -> str:
    birth = "，".join(f"{p}={y}" for p, y in w["birth"].items())
    parents = "，".join(f"{lid}择家长 {q}" for lid, q in w["parents"].items()) or "无亲缘记载"
    leaf = ""
    if "leaf_years" in w:
        leaf = "；叶年 " + "，".join(f"{k}={v}" for k, v in w["leaf_years"].items())
    return f"出生年（{birth}）；{parents}{leaf}"


def family_report(years: dict, links: list, persons: list[str],
                  solutions: list[dict]) -> str:
    lines = ["== 家谱校年 =="]
    lines.append("候选出生年：" + "；".join(f"{p} {years[p]}" for p in persons))
    for link in links:
        lines.append(f"记载 {link['id']}：候选家长 {link['parents']} -> 孩子 {link['child']}，"
                     f"家长生育年龄闭区间 {link['age']}")
    if not solutions:
        lines.append("结论：家谱本身矛盾，不存在任何完整解释。")
        for f in diagnose_family(years, links):
            assign = "，".join(f"{p}={y}" for p, y in f["assignment"].items())
            where = f"记载 {f['link']} " if f["link"] else ""
            lines.append(f"  - 组合（{assign}）：{where}{f['detail']}")
        return "\n".join(lines)

    lines.append(f"结论：共有 {len(solutions)} 套完整解释（出生年向量 "
                 f"{len({tuple(s['birth'][p] for p in persons) for s in solutions})} 种）。")
    lines.append("")
    lines.append("-- 单人可行出生年 --")
    for p in persons:
        fea = person_feasible(solutions, p)
        lines.append(f"{p}：{list(fea)}")
        for y, w in fea.items():
            lines.append(f"    年 {y} 的见证：{_fmt_witness(w)}")
    lines.append("")
    lines.append("-- 两人共同可行出生年组合 --")
    for a in range(len(persons)):
        for b in range(a + 1, len(persons)):
            p1, p2 = persons[a], persons[b]
            fea = pair_feasible(solutions, p1, p2)
            lines.append(f"{p1} / {p2}：{[list(k) for k in fea]}")
            for key, w in fea.items():
                lines.append(f"    组合 {list(key)} 的见证：{_fmt_witness(w)}")
    return "\n".join(lines)


def book_report(result: dict) -> str:
    lines = ["== 簿册断代 =="]
    lines.append(f"馆方年份范围：{result['range']}；装订叶序：{result['leaf_ids']}")
    lines.append(f"相邻叶接缝（年差闭区间）：{result['gaps']}")
    status_text = {
        "ok": "可编成：每叶均有真正可行的年份。",
        "family_contradiction": "家谱本身矛盾，簿册无从编起。",
        "book_impossible": "家谱有解，但此册无法编成。",
    }[result["status"]]
    lines.append(f"结论：{status_text}")
    if result["status"] == "family_contradiction":
        lines.extend("  - " + d for d in result["diagnosis"])
        return "\n".join(lines)

    lines.append("")
    lines.append("-- 每叶全部可行书写年 --")
    for lid in result["leaf_ids"]:
        ys = result["marginals"].get(lid, [])
        lines.append(f"叶 {lid}：{ys if ys else '（无）'}")
        for y, w in result["marginal_witness"].get(lid, {}).items():
            if w is None:
                lines.append(f"    年 {y}：单叶看可落年，但不存在贯穿整册的见证（整册无解）")
            else:
                lines.append(f"    年 {y} 的贯穿见证：{_fmt_witness(w)}")
    lines.append("")
    lines.append("-- 任意两叶联合可行年对（须有贯穿整册见证）--")
    for key, block in result["pairs"].items():
        if not block["values"]:
            lines.append(f"叶 {block['leaves'][0]} / {block['leaves'][1]}：（无联合可行年对）")
            continue
        lines.append(f"叶 {block['leaves'][0]} / {block['leaves'][1]}：{block['values']}")
        for yz, w in block["witness"].items():
            lines.append(f"    年对 ({yz}) 的贯穿见证：{_fmt_witness(w)}")
    if result["status"] == "book_impossible":
        lines.append("")
        lines.append("-- 编不成的原因 --")
        lines.extend("  - " + d for d in result["diagnosis"])
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 各业务入口
# ----------------------------------------------------------------------


def _build_family(raw: dict):
    years, links = validate_family(copy.deepcopy(raw["family"]))
    persons, solutions = solve_family(years, links)
    return years, links, persons, solutions


def _build_book(raw: dict):
    years, links, persons, solutions = _build_family(raw)
    result = solve_book(copy.deepcopy(raw["book"]), persons, solutions)
    return persons, solutions, result


def cmd_family(args) -> None:
    raw = load_json(args.case)
    if args.change is not None:
        raw = apply_change(raw, raw["changes"][args.change])
    years, links, persons, solutions = _build_family(raw)
    if args.json:
        payload = {"persons": persons, "candidate_years": years,
                   "link_count": len(links), "solution_count": len(solutions),
                   "solutions": solutions,
                   "diagnosis": diagnose_family(years, links) if not solutions else []}
        if args.person:
            payload["query"] = {"person": args.person,
                                "feasible_years": list(person_feasible(solutions, args.person))}
        if args.pair:
            payload["query"] = {"pair": args.pair,
                                "feasible_pairs": [list(k) for k in
                                                   pair_feasible(solutions, *args.pair)]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(family_report(years, links, persons, solutions))
    if args.person:
        if args.person not in persons:
            raise InputError(f"名册中无此人：{args.person}")
        fea = person_feasible(solutions, args.person)
        print(f"\n[查询] {args.person} 的可行出生年：{list(fea)}")
        for y, w in fea.items():
            print(f"  年 {y} 见证：{_fmt_witness(w)}")
    if args.pair:
        for p in args.pair:
            _check(p in persons, f"名册中无此人：{p}")
        fea = pair_feasible(solutions, *args.pair)
        print(f"\n[查询] {args.pair[0]} / {args.pair[1]} 的共同可行组合："
              f"{[list(k) for k in fea]}")
        for key, w in fea.items():
            print(f"  组合 {list(key)} 见证：{_fmt_witness(w)}")


def cmd_book(args) -> None:
    raw = load_json(args.case)
    if args.change is not None:
        raw = apply_change(raw, raw["changes"][args.change])
    persons, solutions, result = _build_book(raw)
    if args.json:
        if args.leaves is not None:
            i, j = args.leaves
            key = f"{i}|{j}"
            result = {"leaf_ids": result["leaf_ids"], "status": result["status"],
                      "pair": result["pairs"].get(key),
                      "diagnosis": result["diagnosis"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(book_report(result))
    if args.leaves is not None:
        i, j = args.leaves
        n = len(result["leaf_ids"])
        _check(0 <= i < n and 0 <= j < n and i < j, "叶下标应为 0 起且 i<j")
        block = result["pairs"][f"{i}|{j}"]
        print(f"\n[查询] 叶 {block['leaves'][0]}(#{i}) / {block['leaves'][1]}(#{j}) "
              f"联合可行年对：{block['values']}")
        for yz, w in block["witness"].items():
            if w is not None:
                print(f"  ({yz}) 见证：{_fmt_witness(w)}")


def cmd_run_case(args) -> None:
    raw = load_json(args.case)
    stages = []

    years, links, persons, solutions = _build_family(raw)
    stages.append(("stage1_family_原始家谱", family_report(years, links, persons, solutions),
                   {"persons": persons, "candidate_years": years,
                    "solutions": solutions}))

    _, _, book_result = _build_book(raw)
    stages.append(("stage2_book_原始簿册", book_report(book_result), book_result))

    changes = raw.get("changes", [])
    if len(changes) > 0:
        raw_f = apply_change(raw, changes[0])
        years2, links2, persons2, sol2 = _build_family(raw_f)
        stages.append((f"stage3_family_应用变更0_{changes[0]['path']}",
                       family_report(years2, links2, persons2, sol2),
                       {"change": changes[0], "solutions": sol2}))
    else:
        stages.append(("stage3_family_应用变更0", "（changes 为空，无此阶段）", None))

    if len(changes) > 1:
        raw_b = apply_change(raw, changes[1])  # 仍在原始家谱上改接缝
        _, _, book_result2 = _build_book(raw_b)
        stages.append((f"stage4_book_应用变更1_{changes[1]['path']}",
                       book_report(book_result2), {"change": changes[1], **book_result2}))
    else:
        stages.append(("stage4_book_应用变更1", "（changes 无第二条，无此阶段）", None))

    out_dir = Path(args.out) if args.out else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    for idx, (name, text, payload) in enumerate(stages, 1):
        print(f"\n########## {name} ##########\n{text}")
        if out_dir is not None:
            (out_dir / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
            if payload is not None:
                (out_dir / f"{name}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_dir is not None:
        print(f"\n各阶段文本与 JSON 见证已写入：{out_dir}/")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="家谱校年与无年份工坊簿册断代（纯标准库）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run-case", help="按 case.json 连跑原始/两条变更共四阶段")
    p_run.add_argument("case")
    p_run.add_argument("--out", help="把每阶段 .txt 报告与 .json 见证存入该目录")
    p_run.set_defaults(func=cmd_run_case)

    p_fam = sub.add_parser("family", help="家谱查询")
    p_fam.add_argument("case")
    p_fam.add_argument("--change", type=int, help="应用 changes 中的第 N 条（0 起）")
    p_fam.add_argument("--person", help="只查某人的可行出生年")
    p_fam.add_argument("--pair", nargs=2, metavar=("P1", "P2"), help="查两人共同可行组合")
    p_fam.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_fam.set_defaults(func=cmd_family)

    p_book = sub.add_parser("book", help="簿册编目")
    p_book.add_argument("case")
    p_book.add_argument("--change", type=int, help="应用 changes 中的第 N 条（0 起）")
    p_book.add_argument("--leaves", nargs=2, type=int, metavar=("I", "J"),
                        help="只查第 I、J 叶（0 起）的联合可行年对")
    p_book.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_book.set_defaults(func=cmd_book)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except InputError as exc:
        print(f"输入错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
