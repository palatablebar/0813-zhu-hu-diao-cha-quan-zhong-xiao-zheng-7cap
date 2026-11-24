"""本次可签发的组级发布包。

发布包只引用已经采信、且分组自身对平的记录。暂缓组只保留原因和计数，
不会把未核实的记录带进交付物。
"""

import json
from collections import Counter, defaultdict
from hashlib import sha256

from app.config import RULE_VERSION

SCHEMA = "group-release/1"
FIELDS = (
    "record",
    "case",
    "kind",
    "stratum",
    "households",
    "responded",
    "target",
    "note",
)
# 重复回放与采信记录逐字段一致，不阻塞该组交付。
BENIGN = frozenset({"DUPLICATE_REPLAY"})


def _copy(row):
    return {key: row[key] for key in FIELDS}


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def content_signature(group):
    """同一业务组同一份采信内容和计算结论得到同一签名，用于跨批次去重。

    只签采信记录与计算结论：补齐来源后，内容未变的组继续引用原版本，
    不会因为批次里其他行变化而重复生成。
    """
    payload = {
        "schema": SCHEMA,
        "rule": RULE_VERSION,
        "case": group["case"],
        "decision": group["decision"],
        "records": sorted(group["records"], key=lambda row: row["record"]),
        "measure": group.get("measure"),
    }
    return sha256(_canonical(payload)).hexdigest()


def release_id(group):
    return sha256(
        f"{SCHEMA}:{RULE_VERSION}:{group['case']}:{content_signature(group)}".encode()
    ).hexdigest()


def release_plan(intake, cases):
    """把已采信记录、隔离行和业务组逐项归组，并区分可交付与暂缓。"""
    accepted = defaultdict(list)
    for row in intake["rows"]:
        accepted[row["case"]].append(row)
    isolated = defaultdict(list)
    for item in intake["isolation"]:
        isolated[item["case"]].append(item)

    groups = []
    known = set()
    for case in cases:
        code = case["case"]
        known.add(code)
        rows = sorted(accepted.get(code, []), key=lambda row: row["record"])
        reasons = Counter(item["reason"] for item in isolated.get(code, []))
        blocked = sum(count for reason, count in reasons.items() if reason not in BENIGN)
        faithful = sorted(case["records"]) == [row["record"] for row in rows]

        failures = []
        if case["status"] != "READY":
            failures.append(case["status"])
        if not faithful:
            failures.append("RECORD_MISMATCH")
        failures.extend(
            sorted(reason for reason in reasons if reason not in BENIGN)
        )
        eligible = (
            case["status"] == "READY"
            and faithful
            and not blocked
            and bool(rows)
        )
        group = {
            "case": code,
            "status": "RELEASED" if eligible else "DEFERRED",
            "reasons": sorted(set(failures)) if not eligible else [],
            "decision": case["status"] if faithful else "RECORD_MISMATCH",
            "record_count": len(rows),
            "counts": {
                "input": len(rows) + len(isolated.get(code, [])),
                "accepted": len(rows),
                "isolated": len(isolated.get(code, [])),
                "replay": reasons.get("DUPLICATE_REPLAY", 0),
                "blocking": blocked,
            },
        }
        if eligible:
            group["records"] = [_copy(row) for row in rows]
            group["measure"] = case.get("measure")
            group["content_sha256"] = content_signature(group)
            group["release_id"] = release_id(group)
        groups.append(group)

    released = [group for group in groups if group["status"] == "RELEASED"]
    deferred = [group for group in groups if group["status"] == "DEFERRED"]
    unassigned = [item for item in intake["isolation"] if item["case"] not in known]
    unassigned_ignored = intake["blank"] + intake["repeated"]

    def total(key):
        return sum(group["counts"][key] for group in groups)

    totals = {
        "input": intake["input"],
        "accepted": intake["accepted"],
        "isolated": intake["rejected"],
        "ignored": unassigned_ignored,
        "accounted": intake["accepted"]
        + intake["rejected"]
        + intake["blank"]
        + intake["repeated"],
        "groups": len(groups),
        "released_groups": len(released),
        "released_records": sum(group["counts"]["accepted"] for group in released),
        "released_replay": sum(group["counts"]["replay"] for group in released),
        "deferred_groups": len(deferred),
        "deferred_records": sum(group["counts"]["accepted"] for group in deferred),
        "deferred_isolated": sum(group["counts"]["isolated"] for group in deferred),
        "deferred_replay": sum(group["counts"]["replay"] for group in deferred),
        "unassigned_isolated": len(unassigned),
        "unassigned_ignored": unassigned_ignored,
    }
    checks = {
        "input_split": totals["accounted"] == totals["input"],
        "records_split": totals["accepted"]
        == totals["released_records"] + totals["deferred_records"],
        "groups_split": totals["groups"]
        == totals["released_groups"] + totals["deferred_groups"],
        "line_split": totals["input"]
        == total("input") + totals["unassigned_isolated"] + unassigned_ignored,
        "isolation_split": totals["isolated"]
        == total("isolated") + totals["unassigned_isolated"],
        "replay_split": total("replay")
        == totals["released_replay"] + totals["deferred_replay"],
        "deferred_has_reason": all(group["reasons"] for group in deferred),
        "release_only_verified": all(
            group["decision"] == "READY"
            and group["counts"]["blocking"] == 0
            and len(group["records"]) == group["record_count"]
            and len({row["record"] for row in group["records"]})
            == group["record_count"]
            for group in released
        ),
    }
    return {
        "schema": SCHEMA,
        "groups": groups,
        "released": [group["case"] for group in released],
        "deferred": [
            {
                "case": group["case"],
                "reasons": group["reasons"],
                "counts": group["counts"],
            }
            for group in deferred
        ],
        "unassigned": {
            "isolated": len(unassigned),
            "ignored": unassigned_ignored,
            "reasons": dict(
                sorted(Counter(item["reason"] for item in unassigned).items())
            ),
        },
        "totals": totals,
        "checks": checks,
        "balanced": all(checks.values()),
    }


def packet(group, run_id, created, source_sha256=None):
    """生成单个组的发布包；调用方只传入已判定可交付的组。"""
    if group["status"] != "RELEASED":
        raise ValueError("only reconciled groups can be packaged")
    records = group["records"]
    unique = {row["record"] for row in records}
    verified = {
        "only_accepted_records": len(records) == group["counts"]["accepted"],
        "records_match_case": all(row["case"] == group["case"] for row in records),
        "records_unique": len(unique) == len(records),
        "blocking_isolated": group["counts"]["blocking"],
    }
    signature = content_signature(group)
    return {
        "schema": SCHEMA,
        "id": release_id(group),
        "case": group["case"],
        "run_id": run_id,
        "created": created,
        "rule_version": RULE_VERSION,
        "source_sha256": source_sha256,
        "decision": group["decision"],
        "records": records,
        "record_count": group["record_count"],
        "measure": group.get("measure"),
        "counts": group["counts"],
        "verified": verified,
        "manifest": {"content_sha256": signature},
    }
