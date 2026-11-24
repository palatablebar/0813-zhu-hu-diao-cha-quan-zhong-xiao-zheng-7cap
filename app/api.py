import json

from flask import Blueprint, Response, current_app, jsonify, request

from app.business import DomainIssue
from app.evidence.render import artifact, release_bundle
from app.inputs import read_input
from app.modules.pipeline import run
from app.review.service import execute, review

api = Blueprint("api", __name__, url_prefix="/api")
STAGES = {"intake": 1, "prepare": 2, "calculate": 3, "policy": 4, "balance": 5}


@api.post("/stages/<stage>")
def preview(stage):
    if stage not in STAGES:
        raise DomainIssue("STAGE_UNKNOWN")
    return jsonify(run(read_input(), STAGES[stage]))


@api.route("/runs", methods=["GET", "POST"])
def runs():
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(items=store.list())
    return jsonify(execute(store, read_input()))


@api.route("/runs/<run_id>", methods=["GET", "PATCH"])
def batch(run_id):
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(store.load(run_id))
    return jsonify(review(store, run_id, request.get_json(silent=True)))


@api.get("/runs/<run_id>/evidence")
def export(run_id):
    report = current_app.extensions["runs"].load(run_id)
    return Response(
        artifact(report),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="review-{report["id"][:12]}.json"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/runs/<run_id>/releases")
def run_releases(run_id):
    store = current_app.extensions["runs"]
    store.load(run_id)
    return jsonify(items=store.releases_for(run_id))


@api.get("/runs/<run_id>/bundle")
def run_bundle(run_id):
    store = current_app.extensions["runs"]
    run = store.load(run_id)
    packets = [
        store.load_release(summary["id"])["packet"]
        for summary in store.releases_for(run_id)
    ]
    return Response(
        release_bundle(run, packets),
        mimetype="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="bundle-{run_id[:12]}.json"'
            ),
            "Cache-Control": "no-store",
        },
    )


@api.get("/releases")
def releases():
    return jsonify(items=current_app.extensions["runs"].releases())


@api.get("/releases/<release_id>")
def release_package(release_id):
    item = current_app.extensions["runs"].load_release(release_id)
    body = json.dumps(item["packet"], ensure_ascii=False, sort_keys=True, indent=2)
    return Response(
        body + "\n",
        mimetype="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="release-{item["case"]}-v{item["version"]}.json"'
            ),
            "Cache-Control": "no-store",
        },
    )
