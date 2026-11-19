import csv
import os
import re
import shutil
import time

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import db

XLSX = os.environ.get("TRACKER_XLSX") or os.path.join(os.path.dirname(db.BASE), "Internship Applications Tracker.xlsx")
CSV = os.path.join(db.BASE, "jobs.csv")
HEAD = ["#", "Company", "Role", "Track", "Location", "Status", "Notes", "Source", "Phase / latest update", "Link"]
HFILL = PatternFill("solid", fgColor="1F3A5F")


def map_status(s):
    s = (s or "").strip()
    if s == "Rejected":
        return "Rejected"
    if s == "Applied - pending":
        return "Applied"
    if s == "Applied - assessment":
        return "Assessment"
    if s.startswith("Skipped"):
        return "Skipped"
    if s == "Watchlist":
        return "Watchlist"
    if s == "Not applied - hold":
        return "Hold"
    if s.startswith("Not applied - ") and s.split(" - ", 1)[1].split()[0] in ("ineligible", "likely", "posting", "low"):
        return "Ineligible"
    if s in db.STATUSES:
        return s
    return "To do"


def import_xlsx(path=None):
    path = path or XLSX
    wb = openpyxl.load_workbook(path)
    n = new = 0
    for name in ("Applied", "Not Applied"):
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        hdr = [str(c.value or "").strip() for c in ws[1]]
        col = {h: i for i, h in enumerate(hdr)}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[col.get("Company", 1)]:
                continue
            g = lambda h: (row[col[h]] if h in col and col[h] < len(row) and row[col[h]] is not None else "")
            status = map_status(g("Status"))
            r = {
                "company": str(g("Company")).strip(), "role": str(g("Role")).strip(), "track": str(g("Track")) or "Other",
                "location": str(g("Location")), "status": status, "notes": str(g("Notes")), "source": str(g("Source")),
                "phase": str(g("Phase / latest update") or g("Phase / latest email (as of Oct 14)")),
                "url": str(g("Link")), "status_updated": time.time() if status != "To do" else 0, "fit": 9,
            }
            jid, created = db.upsert(r, tracked=True)
            if not created:
                db.update_job(jid, {"status": status, "notes": r["notes"], "phase": r["phase"]})
            n += 1
            new += created
    return {"rows": n, "new": new}


def style_header(ws, widths):
    for i, w in enumerate(widths, 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HFILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def write_sheet(wb, name, rows, widths):
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name)
    ws.append(HEAD)
    for i, j in enumerate(rows, 1):
        ws.append([i, j["company"], j["role"], j["track"], j["location"], status_label(j["status"]), j["notes"],
                   j["source"], j["phase"], j["url"]])
        if j["url"]:
            c = ws.cell(row=i + 1, column=10)
            c.hyperlink = j["url"]
            c.font = Font(color="0563C1", underline="single")
        for col in (3, 7, 9):
            ws.cell(row=i + 1, column=col).alignment = Alignment(wrap_text=True, vertical="top")
    style_header(ws, widths)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEAD))}{max(ws.max_row, 2)}"
    return ws


def status_label(s):
    return {"Applied": "Applied - pending", "Assessment": "Applied - assessment", "Interview": "Applied - interview",
            "Offer": "Applied - offer", "To do": "Not applied - to do", "Hold": "Not applied - hold",
            "Ineligible": "Not applied - ineligible"}.get(s, s)


def export_xlsx(path=None):
    path = path or XLSX
    jobs = db.all_jobs()
    applied = [j for j in jobs if j["status"] in db.APPLIED_SET]
    order = {"Offer": 0, "Interview": 1, "Assessment": 2, "Applied": 3, "Rejected": 4}
    applied.sort(key=lambda j: (order[j["status"]], j["company"]))
    other_tracked = [j for j in jobs if j["tracked"] and j["status"] not in db.APPLIED_SET]
    discovered = [j for j in jobs if not j["tracked"] and j["status"] == "To do"]
    discovered.sort(key=lambda j: (-j["fit"], j["company"]))
    if os.path.exists(path):
        shutil.copy(path, path + ".bak")
        wb = openpyxl.load_workbook(path)
    else:
        wb = openpyxl.Workbook()
        wb.active.title = "Summary"
    w = [5, 28, 44, 16, 22, 22, 40, 18, 48, 40]
    write_sheet(wb, "Applied", applied, w)
    write_sheet(wb, "Not Applied", other_tracked, w)
    write_sheet(wb, "Discovered", discovered[:3000], w)
    order_names = ["Summary", "Applied", "Not Applied", "Discovered"]
    wb._sheets = [wb[n] for n in order_names if n in wb.sheetnames] + [s for s in wb._sheets if s.title not in order_names]
    if "Summary" in wb.sheetnames:
        s = wb["Summary"]
        for row in s.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    v = re.sub(r"(Applied!|'Not Applied'!)([A-Z])2:\2\d+", lambda m: f"{m.group(1)}{m.group(2)}2:{m.group(2)}2000", v)
                    c.value = v
        s["A2"] = f"Akshith Gandham - synced {time.strftime('%B %d, %Y %H:%M')} from the Intern Tracker website. Counts below are formulas over the Applied and Not Applied tabs."
        s["A1"].value = s["A1"].value or "Summer 2027 Internship Tracker"
    wb.save(path)
    return {"applied": len(applied), "other_tracked": len(other_tracked), "discovered": len(discovered)}


def export_csv():
    jobs = db.all_jobs()
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company", "role", "track", "location", "status", "phase", "notes", "source", "url", "posted", "applied_date", "tracked", "flags"])
        for j in jobs:
            w.writerow([j[k] for k in ("company", "role", "track", "location", "status", "phase", "notes", "source", "url", "posted", "applied_date", "tracked", "flags")])
    return CSV
