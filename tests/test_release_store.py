import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from app.review.service import execute
from app.review.store import Store


def test_parallel_issue_creates_one_version_per_group(clean):
    path = Path(tempfile.mkdtemp()) / "runs.db"
    start = Barrier(4)

    def attempt(_):
        start.wait(3)
        return execute(Store(path), clean)

    with ThreadPoolExecutor(max_workers=4) as threads:
        results = list(threads.map(attempt, range(4)))
    assert len({result["id"] for result in results}) == 1
    assert [(r["case"], r["version"]) for r in Store(path).releases()] == [
        ("0001", 1),
        ("0002", 1),
    ]


def test_issue_is_idempotent_after_storage(store, dirty):
    first = execute(store, dirty)
    latest = store.load(first["id"])
    store.issue(
        first["id"], latest["report"]["release"], latest["report"]["manifest"]["created"]
    )
    assert [(r["case"], r["version"]) for r in store.releases()] == [
        ("0001", 1),
        ("0002", 1),
    ]


def test_unbalanced_plan_is_not_packaged(store, dirty):
    from app.modules.pipeline import run

    plan = json.loads(json.dumps(run(dirty)["release"]))
    plan["balanced"] = False
    store.issue("no-run", plan, "2026-01-01T00:00:00.000+00:00")
    assert store.releases() == []
