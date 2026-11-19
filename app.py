import json
import os
import threading
import time

from flask import Flask, jsonify, request, send_file, send_from_directory

import db
import excel_sync
import gmail_sync
import sources


def load_env():
    p = os.path.join(db.BASE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_env()
db.init()
app = Flask(__name__, static_folder="static")
busy = {}
export_timer = {"t": None}


def schedule_export():
    if os.environ.get("AUTO_EXCEL", "1") != "1":
        return
    if export_timer["t"]:
        export_timer["t"].cancel()

    def run():
        try:
            excel_sync.export_xlsx()
            excel_sync.export_csv()
            db.set_meta("excel_exported", time.time())
            db.set_meta("excel_error", "")
        except Exception as e:
            db.set_meta("excel_error", str(e))

    export_timer["t"] = threading.Timer(4.0, run)
    export_timer["t"].start()


def run_gmail():
    if busy.get("gmail"):
        return {"error": "already running"}
    busy["gmail"] = True
    try:
        res = gmail_sync.sync(int(os.environ.get("GMAIL_DAYS", "45")))
        db.set_meta("gmail_error", "")
        if res["changed"] or res["created"]:
            schedule_export()
        return res
    except Exception as e:
        db.set_meta("gmail_error", str(e))
        return {"error": str(e)}
    finally:
        busy["gmail"] = False


def run_jobs():
    if busy.get("jobs"):
        return {"error": "already running"}
    busy["jobs"] = True
    try:
        stats, new = sources.refresh()
        schedule_export()
        return {"stats": stats, "new": new}
    except Exception as e:
        return {"error": str(e)}
    finally:
        busy["jobs"] = False


def background():
    time.sleep(5)
    last_jobs = float(db.get_meta("jobs_refreshed", "0") or 0)
    while True:
        try:
            if gmail_sync.configured():
                run_gmail()
            if time.time() - last_jobs > 6 * 3600:
                run_jobs()
                last_jobs = time.time()
        except Exception:
            pass
        time.sleep(15 * 60)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


GENERIC = {"american", "federal", "bank", "first", "national", "general", "united", "new", "north"}


def firm_keys(company):
    n = db.norm(company)
    ks = {n}
    w = n.split()
    if w and len(w[0]) >= 5 and w[0] not in GENERIC:
        ks.add(w[0])
    for al in gmail_sync.aliases_for(company):
        if len(al) >= 4 and al not in GENERIC:
            ks.add(al)
    return ks


@app.route("/api/jobs")
def jobs():
    rows = db.all_jobs()
    applied = set()
    for j in rows:
        if j["status"] in db.APPLIED_SET:
            applied |= firm_keys(j["company"])
    for j in rows:
        j["firm_applied"] = bool(firm_keys(j["company"]) & applied) and j["status"] not in db.APPLIED_SET
    return jsonify(rows)


@app.route("/api/jobs", methods=["POST"])
def add_job():
    d = request.get_json(force=True)
    row = {k: d.get(k, "") for k in ("company", "role", "track", "location", "status", "notes", "url", "phase")}
    row["source"] = "Manual"
    row["status"] = row["status"] or "To do"
    row["track"] = row["track"] or sources.classify(row["role"])
    row["fit"] = 9
    if not row["company"]:
        return jsonify({"error": "company required"}), 400
    jid, _ = db.upsert(row, tracked=True)
    if row["status"] != "To do":
        db.update_job(jid, {"status": row["status"]})
    schedule_export()
    return jsonify(db.get_job(jid))


@app.route("/api/jobs/<int:jid>", methods=["PATCH"])
def patch_job(jid):
    d = request.get_json(force=True)
    if "status" in d or "notes" in d or "phase" in d:
        d.setdefault("tracked", 1)
    db.update_job(jid, d)
    schedule_export()
    return jsonify(db.get_job(jid))


@app.route("/api/jobs/<int:jid>", methods=["DELETE"])
def del_job(jid):
    db.delete_job(jid)
    schedule_export()
    return jsonify({"ok": True})


@app.route("/api/emails")
def emails():
    with db.lock, db.conn() as c:
        rows = [dict(r) for r in c.execute("select * from emails order by date desc limit 300")]
    return jsonify(rows)


@app.route("/api/emails/<path:msgid>/assign", methods=["POST"])
def assign_email(msgid):
    d = request.get_json(force=True)
    jid = int(d["job_id"])
    with db.lock, db.conn() as c:
        e = c.execute("select * from emails where msgid=?", (msgid,)).fetchone()
        if not e:
            return jsonify({"error": "not found"}), 404
        c.execute("update emails set job_id=?, resolved=1, company=? where msgid=?",
                  (jid, db.get_job(jid)["company"], msgid))
    job = db.get_job(jid)
    gmail_sync.apply_event(e["kind"], e["date"], job, e["subject"])
    schedule_export()
    return jsonify({"ok": True})


@app.route("/api/sync/gmail", methods=["POST"])
def sync_gmail():
    return jsonify(run_gmail())


@app.route("/api/sync/jobs", methods=["POST"])
def sync_jobs():
    threading.Thread(target=run_jobs, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/sync/excel/import", methods=["POST"])
def excel_import():
    try:
        return jsonify(excel_sync.import_xlsx())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/excel/export", methods=["POST"])
def excel_export():
    try:
        r = excel_sync.export_xlsx()
        excel_sync.export_csv()
        db.set_meta("excel_exported", time.time())
        return jsonify(r)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export.csv")
def csv_download():
    return send_file(excel_sync.export_csv(), as_attachment=True, download_name="jobs.csv")


@app.route("/api/status")
def status():
    return jsonify({
        "gmail_configured": gmail_sync.configured(),
        "gmail_user": gmail_sync.creds()[0],
        "gmail_synced": float(db.get_meta("gmail_synced", "0") or 0),
        "gmail_error": db.get_meta("gmail_error"),
        "jobs_refreshed": float(db.get_meta("jobs_refreshed", "0") or 0),
        "jobs_stats": json.loads(db.get_meta("jobs_stats", "{}") or "{}"),
        "excel_exported": float(db.get_meta("excel_exported", "0") or 0),
        "excel_error": db.get_meta("excel_error"),
        "busy": {k: v for k, v in busy.items() if v},
        "statuses": db.STATUSES,
    })


if __name__ == "__main__":
    if not db.all_jobs() and os.path.exists(excel_sync.XLSX):
        excel_sync.import_xlsx()
    threading.Thread(target=background, daemon=True).start()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5055")), threaded=True)
