import os
import re
import sqlite3
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "tracker.db")
lock = threading.RLock()

STATUSES = ["To do", "Applied", "Assessment", "Interview", "Offer", "Rejected",
            "Skipped", "Ineligible", "Watchlist", "Hold"]
APPLIED_SET = {"Applied", "Assessment", "Interview", "Offer", "Rejected"}
RANK = {"To do": 0, "Applied": 1, "Assessment": 2, "Interview": 3, "Offer": 4}

SCHEMA = """
create table if not exists jobs (
    id integer primary key autoincrement,
    key text unique,
    company text not null,
    role text not null default '',
    track text default 'Other',
    location text default '',
    status text default 'To do',
    phase text default '',
    notes text default '',
    source text default '',
    url text default '',
    posted text default '',
    added text default '',
    applied_date text default '',
    status_updated real default 0,
    tracked integer default 0,
    flags text default '',
    fit integer default 0
);
create table if not exists emails (
    msgid text primary key,
    date real,
    sender text,
    subject text,
    kind text,
    company text,
    job_id integer,
    note text,
    resolved integer default 0
);
create table if not exists meta (k text primary key, v text);
create index if not exists idx_jobs_company on jobs(company);
"""


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with lock, conn() as c:
        c.executescript(SCHEMA)


def get_meta(k, default=""):
    with lock, conn() as c:
        r = c.execute("select v from meta where k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_meta(k, v):
    with lock, conn() as c:
        c.execute("insert into meta(k,v) values(?,?) on conflict(k) do update set v=excluded.v", (k, str(v)))


SUFFIX = {"inc", "llc", "lp", "ltd", "corp", "co", "company", "the", "plc", "llp", "group", "holdings"}


def norm(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    w = [x for x in s.split() if x not in SUFFIX]
    return " ".join(w)


def make_key(company, role, location=""):
    loc = (location or "").split(";")[0].split("/")[0].strip().lower()
    return f"{norm(company)}|{norm(role)}|{re.sub(r'[^a-z]', '', loc)[:12]}"


def upsert(row, tracked=None):
    now = time.time()
    key = make_key(row["company"], row.get("role", ""), row.get("location", ""))
    with lock, conn() as c:
        cur = c.execute("select * from jobs where key=?", (key,)).fetchone()
        if cur:
            upd = {}
            if row.get("url") and not cur["url"]:
                upd["url"] = row["url"]
            if row.get("posted") and not cur["posted"]:
                upd["posted"] = row["posted"]
            if row.get("track") and cur["track"] in ("", "Other", None):
                upd["track"] = row["track"]
            if tracked:
                upd["tracked"] = 1
            if upd:
                sets = ",".join(f"{k}=?" for k in upd)
                c.execute(f"update jobs set {sets} where id=?", (*upd.values(), cur["id"]))
            return cur["id"], False
        cols = ["key", "company", "role", "track", "location", "status", "phase", "notes", "source", "url",
                "posted", "added", "applied_date", "status_updated", "tracked", "flags", "fit"]
        d = {
            "key": key, "company": row["company"], "role": row.get("role", ""),
            "track": row.get("track", "Other"), "location": row.get("location", ""),
            "status": row.get("status", "To do"), "phase": row.get("phase", ""),
            "notes": row.get("notes", ""), "source": row.get("source", ""), "url": row.get("url", ""),
            "posted": row.get("posted", ""), "added": time.strftime("%Y-%m-%d"),
            "applied_date": row.get("applied_date", ""), "status_updated": row.get("status_updated", 0),
            "tracked": 1 if tracked else int(row.get("tracked", 0)), "flags": row.get("flags", ""),
            "fit": row.get("fit", 0),
        }
        cur = c.execute(f"insert into jobs({','.join(cols)}) values({','.join('?' * len(cols))})",
                        [d[k] for k in cols])
        return cur.lastrowid, True


def all_jobs():
    with lock, conn() as c:
        return [dict(r) for r in c.execute("select * from jobs order by tracked desc, fit desc, company")]


def get_job(jid):
    with lock, conn() as c:
        r = c.execute("select * from jobs where id=?", (jid,)).fetchone()
    return dict(r) if r else None


EDITABLE = {"company", "role", "track", "location", "status", "phase", "notes", "url", "applied_date", "tracked", "flags"}


def update_job(jid, fields, from_email=False, when=None):
    fields = {k: v for k, v in fields.items() if k in EDITABLE}
    if not fields:
        return
    if "status" in fields:
        fields["status_updated"] = when or time.time()
        if fields["status"] in APPLIED_SET:
            fields["tracked"] = 1
            cur = get_job(jid)
            if cur and not cur["applied_date"] and "applied_date" not in fields:
                fields["applied_date"] = time.strftime("%Y-%m-%d", time.localtime(fields["status_updated"]))
    sets = ",".join(f"{k}=?" for k in fields)
    with lock, conn() as c:
        c.execute(f"update jobs set {sets} where id=?", (*fields.values(), jid))


def delete_job(jid):
    with lock, conn() as c:
        c.execute("delete from jobs where id=?", (jid,))
