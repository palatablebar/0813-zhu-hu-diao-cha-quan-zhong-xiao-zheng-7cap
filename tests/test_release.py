from app.modules.pipeline import run
from app.review.service import execute
from conftest import csv_data


def plan(data):
    return run(data)["release"]


def group(data, case):
    return next(g for g in plan(data)["groups"] if g["case"] == case)


def test_dirty_releases_ready_groups_only(dirty):
    result = plan(dirty)
    assert result["released"] == ["0001", "0002"]
    assert [item["case"] for item in result["deferred"]] == ["0003", "0004"]
    assert {item["case"]: item["reasons"] for item in result["deferred"]} == {
        "0003": ["NO_RESPONDENTS"],
        "0004": ["MISMATCH"],
    }


def test_deferred_groups_keep_reason_and_counts(dirty):
    deferred = {item["case"]: item for item in plan(dirty)["deferred"]}
    assert deferred["0004"]["counts"] == {
        "input": 2,
        "accepted": 2,
        "isolated": 0,
        "replay": 0,
        "blocking": 0,
    }


def test_totals_reconcile_line_by_line(dirty):
    result = plan(dirty)
    totals, checks = result["totals"], result["checks"]
    assert totals["input"] == totals["accepted"] + totals["isolated"] + totals["ignored"]
    assert totals["accepted"] == (
        totals["released_records"] + totals["deferred_records"]
    )
    assert totals["groups"] == totals["released_groups"] + totals["deferred_groups"]
    assert all(checks.values()) and result["balanced"]


def test_clean_batch_releases_every_group(clean):
    result = plan(clean)
    assert result["deferred"] == []
    assert result["totals"]["deferred_records"] == 0
    assert result["balanced"]


def test_release_records_are_accepted_and_in_group(dirty):
    report = run(dirty)
    accepted = {
        row["record"]: row["case"]
        for row in report["release"]["groups"][0]["records"]
    }
    assert set(accepted) == {"000101", "000102", "000103", "000104", "000105"}
    for released in (group(dirty, "0001"), group(dirty, "0002")):
        assert all(row["case"] == released["case"] for row in released["records"])
        assert released["counts"]["blocking"] == 0
        assert released["decision"] == "READY"


def test_isolated_rows_never_enter_packet(store, dirty):
    run_row = execute(store, dirty)
    rejected = {
        item["record"]
        for item in run_row["report"]["intake"]["isolation"]
        if item["reason"] != "DUPLICATE_REPLAY"
    }
    assert rejected == {"ERR1", "ERR2", "ERR3"}
    for summary in run_row["releases"]:
        packet = store.load_release(summary["id"])["packet"]
        records = {row["record"] for row in packet["records"]}
        assert not records & rejected
        assert packet["verified"]["only_accepted_records"] is True


def test_blocking_isolation_defers_group(store):
    data = csv_data(
        [
            ["000501", "0005", "census", "1", "0", "0", "100", "框"],
            ["000502", "0005", "wave", "1", "100", "50", "0", "波"],
            ["000503", "0005", "wave", "1", "N/A", "0", "0", "缺测"],
        ]
    )
    result = plan(data)
    assert result["released"] == []
    assert result["deferred"][0]["case"] == "0005"
    assert "MISSING_NUMBER" in result["deferred"][0]["reasons"]


def test_rerun_does_not_duplicate_release(store, dirty):
    first = execute(store, dirty)
    second = execute(store, dirty)
    assert first["id"] == second["id"]
    assert [(r["case"], r["version"]) for r in store.releases()] == [
        ("0001", 1),
        ("0002", 1),
    ]


def test_fix_and_rerun_reuses_unchanged_group(store, dirty):
    original = execute(store, dirty)
    before = {summary["case"]: summary["id"] for summary in original["releases"]}

    fixed = (
        dirty.replace(b"000401,0004,census,1,0,0,20,", b"000401,0004,census,1,0,0,16,")
    )
    after = execute(store, fixed)
    assert after["id"] != original["id"]
    assert after["report"]["release"]["released"] == ["0001", "0002", "0004"]
    now = {summary["case"]: summary for summary in after["releases"]}
    assert now["0001"]["id"] == before["0001"] and now["0001"]["version"] == 1
    assert now["0002"]["id"] == before["0002"] and now["0002"]["version"] == 1
    assert now["0004"]["version"] == 1
    assert len(store.releases()) == 3
    # 旧批次与旧签发仍可回读。
    assert store.load(original["id"])["report"]["release"]["released"] == [
        "0001",
        "0002",
    ]
    assert store.load_release(before["0001"])["packet"]["case"] == "0001"


def test_changed_records_bump_version(store, dirty):
    first = execute(store, dirty)
    old = next(r for r in first["releases"] if r["case"] == "0001")
    assert old["version"] == 1

    changed = dirty.replace(
        "000103,0001,wave,1,30,15,0,补录记录".encode(),
        "000103,0001,wave,1,30,15,0,补录记录校订".encode(),
    )
    second = execute(store, changed)
    new = next(r for r in second["releases"] if r["case"] == "0001")
    assert new["version"] == 2 and new["id"] != old["id"]
    assert new["counts"]["accepted"] == 5
    # 0002 未改动，继续引用原版本。
    assert next(r for r in second["releases"] if r["case"] == "0002")["version"] == 1
    # 旧签发不受影响。
    assert store.load_release(old["id"])["packet"]["record_count"] == 5


def test_release_endpoints(client, store):
    run = client.post("/api/runs", data={"sample": "dirty"}).json
    summary = run["releases"][0]
    listing = client.get("/api/releases")
    assert listing.status_code == 200
    assert {item["case"] for item in listing.json["items"]} == {"0001", "0002"}
    packet = client.get("/api/releases/" + summary["id"])
    assert packet.status_code == 200
    assert "attachment" in packet.headers["Content-Disposition"]
    assert packet.json["schema"] == "group-release/1"
    assert packet.json["id"] == summary["id"]
    assert packet.json["case"] == summary["case"]
    assert client.get("/api/releases/unknown").status_code == 404


def test_deferred_group_has_no_release_id(dirty):
    for deferred in plan(dirty)["deferred"]:
        assert "records" not in deferred
        assert deferred["reasons"]


def test_bundle_carries_released_packets_and_deferrals(client):
    run = client.post("/api/runs", data={"sample": "dirty"}).json
    response = client.get("/api/runs/" + run["id"] + "/bundle")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    bundle = response.json
    assert bundle["schema"] == "group-release-bundle/1"
    assert [packet["case"] for packet in bundle["released"]] == ["0001", "0002"]
    assert [item["case"] for item in bundle["deferred"]] == ["0003", "0004"]
    assert bundle["balanced"] is True
    assert bundle["totals"]["released_records"] + bundle["totals"][
        "deferred_records"
    ] == bundle["totals"]["accepted"]
    assert client.get("/api/runs/unknown/bundle").status_code == 404


def test_packet_is_deterministic(store, clean):
    run = execute(store, clean)
    first = store.load_release(run["releases"][0]["id"])["packet"]
    again = store.load_release(run["releases"][0]["id"])["packet"]
    assert first == again


def test_content_signature_survives_different_sources(store, clean, dirty):
    clean_release = execute(store, clean)["releases"][0]
    dirty_release = execute(store, dirty)["releases"][0]
    assert clean_release["id"] == dirty_release["id"]
    assert clean_release["version"] == dirty_release["version"] == 1
    assert len(store.releases()) == 2
