import json


def artifact(run):
    report = run["report"]
    packet = {
        "schema": "review-evidence/1",
        "manifest": report["manifest"],
        "balance": report["balance"],
        "release": report.get("release"),
        "releases": run.get("releases", []),
        "cases": report["cases"],
        "intake": report["intake"],
        "review": {key: run[key] for key in ("status", "revision", "note", "reviewed")},
    }
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def release_bundle(run, packets):
    """本次批次的组级发布包：已签发组逐包收录，暂缓组只留原因与计数。"""
    report = run["report"]
    plan = report.get("release") or {}
    bundle = {
        "schema": "group-release-bundle/1",
        "run_id": run["id"],
        "created": report["manifest"]["created"],
        "rule_version": report["manifest"]["version"],
        "source_sha256": report["manifest"]["sha256"],
        "manifest": {"run_id": run["id"], "sha256": report["manifest"]["sha256"]},
        "released": packets,
        "deferred": plan.get("deferred", []),
        "unassigned": plan.get("unassigned", {}),
        "totals": plan.get("totals"),
        "checks": plan.get("checks"),
        "balanced": plan.get("balanced", False),
        "review": {key: run[key] for key in ("status", "revision", "note", "reviewed")},
    }
    return (
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
