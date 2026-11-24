import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT
);
CREATE TABLE IF NOT EXISTS releases (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, version INTEGER NOT NULL,
    content TEXT NOT NULL, run_id TEXT NOT NULL, packet TEXT NOT NULL,
    created TEXT NOT NULL, UNIQUE(case_id, version), UNIQUE(case_id, content)
);
CREATE TABLE IF NOT EXISTS issuance (
    run_id TEXT NOT NULL, release_id TEXT NOT NULL,
    PRIMARY KEY (run_id, release_id)
);"""


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            yield db

    # -- 批次 ---------------------------------------------------------------

    def register(self, run_id, report):
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,report,created) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
                (
                    run_id,
                    json.dumps(report, ensure_ascii=False),
                    report["manifest"]["created"],
                ),
            )
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        result = dict(row)
        result["report"] = json.loads(result["report"])
        result["releases"] = self.releases_for(run_id)
        return result

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50"
                )
            ]

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?",
                (status, note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
        return self.load(run_id)

    # -- 组级发布 -----------------------------------------------------------

    def issue(self, run_id, plan, now, source_sha256=None):
        """为可交付组登记发布版本；同组同内容复用已有版本，不重复生成。"""
        from app.modules.release import content_signature, packet

        if plan is None or not plan.get("balanced"):
            # 逐项对账不相合时，宁可不出包，也不交付未经核实的记录。
            return self.releases_for(run_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for group in plan["groups"]:
                if group["status"] != "RELEASED" or group["counts"]["blocking"]:
                    continue
                signature = content_signature(group)
                found = db.execute(
                    "SELECT id,version FROM releases WHERE case_id=? AND content=?",
                    (group["case"], signature),
                ).fetchone()
                release_id = found["id"] if found else None
                if release_id is None:
                    version = db.execute(
                        "SELECT COALESCE(MAX(version),0)+1 FROM releases WHERE case_id=?",
                        (group["case"],),
                    ).fetchone()[0]
                    body = packet(group, run_id, now, source_sha256)
                    body["version"] = version
                    release_id = body["id"]
                    try:
                        db.execute(
                            "INSERT INTO releases(id,case_id,version,content,run_id,packet,created)"
                            " VALUES (?,?,?,?,?,?,?)",
                            (
                                body["id"],
                                group["case"],
                                version,
                                signature,
                                run_id,
                                json.dumps(body, ensure_ascii=False),
                                now,
                            ),
                        )
                    except sqlite3.IntegrityError:
                        release_id = db.execute(
                            "SELECT id FROM releases WHERE case_id=? AND content=?",
                            (group["case"], signature),
                        ).fetchone()["id"]
                db.execute(
                    "INSERT OR IGNORE INTO issuance(run_id,release_id) VALUES (?,?)",
                    (run_id, release_id),
                )
        return self.releases_for(run_id)

    def releases_for(self, run_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT r.id,r.case_id,r.version,r.created,r.run_id,r.packet"
                " FROM releases r JOIN issuance i ON i.release_id=r.id"
                " WHERE i.run_id=? ORDER BY r.case_id,r.version",
                (run_id,),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def releases(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,case_id,version,created,run_id,packet FROM releases"
                " ORDER BY case_id,version"
            ).fetchall()
        return [self._summary(row) for row in rows]

    def load_release(self, release_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT id,case_id,version,created,run_id,packet FROM releases WHERE id=?",
                (release_id,),
            ).fetchone()
        if row is None:
            raise DomainIssue("RELEASE_NOT_FOUND")
        result = self._summary(row)
        result["packet"] = json.loads(row["packet"])
        return result

    @staticmethod
    def _summary(row):
        packet = json.loads(row["packet"])
        return {
            "id": row["id"],
            "case": row["case_id"],
            "version": row["version"],
            "created": row["created"],
            "run_id": row["run_id"],
            "status": "ISSUED",
            "record_count": packet.get("record_count"),
            "counts": packet.get("counts"),
        }
