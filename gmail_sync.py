import email
import imaplib
import os
import re
import time
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, parseaddr

import db

SKIP_SENDERS = ("reddit", "linkedin.com", "indeed", "simplify", "investopedia", "edx", "acorns", "grammarly",
                "sallie", "unidays", "lafitness", "asu.edu", "asunews", "pima", "studentaid", "ed.gov",
                "chase sapphire", "michael yan", "qhack", "reply.chase")
REJECT = re.compile(r"unfortunately|not (be )?(moving|move|proceed)|regret to inform|decided not to|unable to (move|proceed|offer)|"
                    r"will not be (moving|progressing)|not (to )?proceed|difficult decision|decision on (your )?application|"
                    r"we are sorry to let you|no longer (being )?considered|not selected|other candidates|pursue other", re.I)
ASSESS_DONE = re.compile(r"thank(s| you) for (completing|taking)|assessment complete|we've received your video|submission confirmation|"
                         r"we.ve sent your submission|completed (the|your)", re.I)
ASSESS = re.compile(r"assessment|hackerrank|codesignal|hirevue|coding (challenge|test)|invited to take|criteria|"
                    r"online test|video interview|behavioral assessment|predictive index|mettl|canditech|karat", re.I)
INTERVIEW = re.compile(r"interview|superday|phone screen|schedule a (call|time)|meet with|final round|next round", re.I)
OFFER = re.compile(r"pleased to offer|offer of employment|extend(ing)? (you )?an offer|internship offer", re.I)
APPLIED = re.compile(r"thank(s| you) for (applying|your (application|interest))|received your application|application (received|confirmation)|"
                     r"we have received your|successfully (received|submitted)|application (has been )?received|your application (is|was)", re.I)

EXTRA_ALIASES = {
    "susquehanna international group": ["susquehanna", "sig"], "federal reserve bank of san francisco": ["federal reserve", "frb"],
    "millennium": ["millennium", "mlp"], "kensho": ["kensho", "s p global"], "hudson river trading": ["hudson river", "hrt"],
    "scm": ["stevens capital"], "chicago trading company": ["chicago trading", "ctc"], "neuberger berman": ["neuberger"],
    "jpmorgan chase": ["jpmorgan", "jpmorganchase", "jp morgan"], "american express": ["amex", "american express"],
    "interactive brokers": ["interactive brokers", "ibkr", "ibforce", "ibg llc"], "bank of america": ["bank of america"],
    "tiktok": ["tiktok"], "bytedance": ["bytedance"], "citadel securities": ["citadel securities"],
    "citadel": ["citadel"], "imc trading": ["imc"], "aqr capital management": ["aqr"], "jump trading": ["jump trading"], "google": ["google"], "tsmc": ["tsmc"], "ibm": ["ibm"],
    "tower research capital": ["tower research", "tower"], "dv trading": ["dv trading"], "mckinsey": ["mckinsey"],
    "anthropic": ["anthropic"], "intuit": ["intuit"], "adobe": ["adobe"], "xanadu": ["xanadu"],
}
ROLE_STOP = {"intern", "internship", "summer", "2027", "the", "and", "of", "analyst", "program", "role", "quantitative", "quant"}


def creds():
    user = os.environ.get("GMAIL_USER", "")
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    return user, pw


def configured():
    u, p = creds()
    return bool(u and p)


def dh(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def body_text(msg, limit=3000):
    parts = []
    for p in msg.walk():
        if p.get_content_type() in ("text/plain", "text/html"):
            try:
                raw = p.get_payload(decode=True) or b""
                t = raw.decode(p.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if p.get_content_type() == "text/html":
                t = re.sub(r"<(script|style).*?</\1>", " ", t, flags=re.S | re.I)
                t = re.sub(r"<[^>]+>", " ", t)
            parts.append(re.sub(r"\s+", " ", t))
        if sum(len(x) for x in parts) > limit:
            break
    return " ".join(parts)[:limit]


def aliases_for(company):
    n = db.norm(company)
    al = {n}
    if len(n.split()) > 1 and len(n.split()[0]) >= 5:
        al.add(n.split()[0])
    for k, v in EXTRA_ALIASES.items():
        if n.startswith(k) or k == n:
            al.update(v)
    paren = re.search(r"\((.*?)\)", company)
    if paren:
        al.add(db.norm(paren.group(1)))
    return {a for a in al if a}


def build_alias_index(jobs):
    idx = {}
    for j in jobs:
        for a in aliases_for(j["company"]):
            idx.setdefault(a, set()).add(db.norm(j["company"]))
    return idx


def match_company(text, idx):
    t = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
    tc = re.sub(r"[^a-z0-9]", "", text.lower())
    best = None
    for a, comps in idx.items():
        if len(a) < 3 and a not in ("ibm",):
            continue
        ac = a.replace(" ", "")
        if f" {a} " in t or (len(ac) >= 5 and ac in tc):
            if best is None or len(a) > len(best[0]):
                best = (a, comps)
    return best[1] if best else None


def classify(subject, body, sender):
    text = f"{subject} {body[:600]}"
    s = subject
    if REJECT.search(text):
        return "Rejected"
    if OFFER.search(text):
        return "Offer"
    if ASSESS_DONE.search(s) or (ASSESS_DONE.search(text) and ASSESS.search(text)):
        return "Assessment"
    if ASSESS.search(s):
        return "Assessment"
    if APPLIED.search(s) or APPLIED.search(body[:300]):
        return "Applied"
    if INTERVIEW.search(s):
        return "Interview"
    if ASSESS.search(text):
        return "Assessment"
    return None


def guess_company(sender_name, subject):
    for pat in (r"applying (?:to|for|at) ([A-Z][\w&.\- ]{2,40}?)(?:[!.,]|$| for | - )",
                r"interest in ([A-Z][\w&.\- ]{2,40}?)(?:[!.,]|$)", r"application to ([A-Z][\w&.\- ]{2,40}?)(?:[!.,]|$)"):
        m = re.search(pat, subject)
        if m:
            return m.group(1).strip()
    n = re.sub(r"(?i)\b(no-?reply|noreply|careers?|recruit\w*|talent|jobs|hr|team|workday|do-not-reply|notifications?)\b", "", sender_name).strip(" -@.")
    return n if len(n) > 2 else ""


def pick_job(cands, text, kind):
    if len(cands) == 1:
        return cands[0]
    toks = {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in ROLE_STOP}
    scored = []
    for j in cands:
        rt = {w for w in re.findall(r"[a-z]{3,}", j["role"].lower()) if w not in ROLE_STOP}
        scored.append((len(rt & toks), j))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    active = [j for j in cands if j["status"] in db.APPLIED_SET and j["status"] != "Rejected"]
    if kind != "Applied" and len(active) == 1:
        return active[0]
    if kind == "Applied":
        todo = [j for j in cands if j["status"] == "To do"]
        if len(todo) == 1 and not [j for j in cands if j["status"] in db.APPLIED_SET]:
            return todo[0]
    return None


def apply_event(kind, when, job, subject):
    cur = job["status"]
    if when <= (job["status_updated"] or 0):
        return False
    if kind == "Rejected":
        new = "Rejected"
    elif cur in ("Rejected", "Ineligible", "Skipped") and kind != "Applied":
        return False
    elif cur in db.RANK and db.RANK.get(kind, 0) <= db.RANK[cur] and not (kind == cur):
        return False
    else:
        new = kind
    if new == cur:
        return False
    phase = f"{time.strftime('%b %d', time.localtime(when))}: {subject[:90]}"
    db.update_job(job["id"], {"status": new, "phase": phase}, from_email=True, when=when)
    return True


def label_and_star(M, nums):
    label = os.environ.get("GMAIL_LABEL", "Jobs")
    done = 0
    for k in range(0, len(nums), 100):
        chunk = b",".join(nums[k:k + 100]).decode()
        M.store(chunk, "+X-GM-LABELS", f'("{label}")')
        M.store(chunk, "+FLAGS", r"(\Flagged)")
        done += len(nums[k:k + 100])
    return done


def sync(days=45, progress=None):
    user, pw = creds()
    if not (user and pw):
        raise RuntimeError("Set GMAIL_USER and GMAIL_APP_PASSWORD in InternTracker/.env")
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(user, pw)
    M.select('"[Gmail]/All Mail"')
    q = f'newer_than:{days}d (application OR applying OR assessment OR interview OR candidacy OR "thank you for your interest" OR hackerrank OR codesignal OR hirevue OR offer OR "your submission")'
    typ, data = M.search(None, "X-GM-RAW", '"' + q.replace("\\", "\\\\").replace('"', '\\"') + '"')
    ids = data[0].split()
    jobs = db.all_jobs()
    idx = build_alias_index([j for j in jobs if j["tracked"]])
    changed = created = 0
    seen = set()
    with db.lock, db.conn() as c:
        seen = {r["msgid"] for r in c.execute("select msgid from emails")}
    to_label = []
    for i in ids:
        typ, hd = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        hmid = ""
        if hd and hd[0] and isinstance(hd[0], tuple):
            hm = email.message_from_bytes(hd[0][1])
            hmid = (hm.get("Message-ID") or "").strip()
        if hmid and hmid in seen:
            to_label.append(i)
            continue
        typ, md = M.fetch(i, "(BODY.PEEK[])")
        if not md or not md[0]:
            continue
        msg = email.message_from_bytes(md[0][1])
        mid = (msg.get("Message-ID") or f"gm-{i.decode()}").strip()
        if mid in seen:
            to_label.append(i)
            continue
        subject = dh(msg.get("Subject"))
        sname, saddr = parseaddr(dh(msg.get("From")))
        sender = f"{sname} <{saddr}>"
        low = sender.lower()
        try:
            when = parsedate_to_datetime(msg.get("Date")).timestamp()
        except Exception:
            when = time.time()
        if any(s in low for s in SKIP_SENDERS):
            continue
        body = body_text(msg)
        kind = classify(subject, body, sender)
        if not kind:
            continue
        to_label.append(i)
        comps = match_company(f"{sender} {subject} {body[:400]}", idx)
        note = ""
        job = None
        if comps:
            cands = [j for j in db.all_jobs() if db.norm(j["company"]) in comps and j["tracked"]]
            job = pick_job(cands, f"{subject} {body[:500]}", kind)
            if not job:
                note = "ambiguous role"
        elif kind == "Applied":
            comp = guess_company(sname, subject)
            if comp:
                role = re.sub(r"(?i)^(thank you for applying( to)?|application received[:\- ]*)", "", subject).strip()[:100]
                jid, new = db.upsert({"company": comp, "role": role or "Intern", "track": "Other", "source": "Gmail",
                                      "status": "To do", "tracked": 1}, tracked=True)
                job = db.get_job(jid)
                created += new
                idx = build_alias_index([j for j in db.all_jobs() if j["tracked"]])
        if job and apply_event(kind, when, job, subject):
            changed += 1
        with db.lock, db.conn() as c:
            c.execute("insert or ignore into emails(msgid,date,sender,subject,kind,company,job_id,note,resolved) values(?,?,?,?,?,?,?,?,?)",
                      (mid, when, sender, subject, kind, job["company"] if job else "", job["id"] if job else None,
                       note or ("" if job else "no company match"), 1 if job else 0))
        if progress:
            progress(subject)
    labeled = label_and_star(M, to_label)
    M.logout()
    db.set_meta("gmail_synced", time.time())
    return {"scanned": len(ids), "changed": changed, "created": created, "labeled": labeled}
