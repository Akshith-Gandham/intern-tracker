import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import db

UA = {"User-Agent": "Mozilla/5.0 InternTracker"}
US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())

SIMPLIFY = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
NWFT = "https://raw.githubusercontent.com/northwesternfintech/2027QuantInternships/main/README.md"
README_REPOS = [
    "vanshb03/Summer2027-Internships",
    "ouckah/Summer2027-Internships",
    "cvrve/Summer2027-Internships",
]

GREENHOUSE = ["janestreet", "hudsonrivertrading", "jumptrading", "optiver", "twosigma", "akunacapital", "drweng",
              "point72", "wolverine", "imc", "anthropic", "scaleai", "databricks", "stripe", "coinbase", "robinhood",
              "airbnb", "figma", "plaid", "affirm", "brex", "pinterest", "lyft", "cloudflare", "datadog", "anduril",
              "cerebrassystems", "togetherai", "cohere", "ionq", "rigetti", "aquaticcapitalmanagement", "arrowstreetcapital",
              "chicagotradingcompany", "cubist", "virtu", "squarepointcapital", "oldmissioncapital", "peak6",
              "flowtraders", "mantleinc", "xtxmarkets", "gresearch", "qubit", "sigmacomputing", "waymo", "nuro",
              "mongodb", "snowflake", "elastic", "duolingo", "reddit", "instacart", "doordash", "block", "uber",
              "openai", "deepmind", "tempus", "janestreet2", "radixtrading", "cmegroup", "tradeweb", "geneva"]
LEVER = ["palantir", "ansatzcapital", "belvederetrading", "quantinuum", "xanadu", "psiquantum", "rigetti", "ionq",
         "spotify", "mistral", "wealthfront", "metabase", "kensho", "ripple", "kraken", "zoox", "shieldai",
         "plaid", "atlassian", "anyscale", "weride", "hrt", "tower-research", "tower"]
ASHBY = ["openai", "ramp", "notion", "linear", "cursor", "perplexity", "cohere", "together", "modal", "harvey",
         "anthropic", "elevenlabs", "runway", "character", "sesame", "characterai", "decagon", "glean", "sierra",
         "mercor", "baseten", "hex", "retool", "vercel", "supabase", "mistral", "xai", "thinkingmachines", "periodic",
         "quantco", "gsr", "bullish", "flowdesk", "keyrock", "wintermute", "hudson-river-trading"]


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def getj(url, timeout=40):
    return json.loads(get(url, timeout).decode("utf-8", "replace"))


def classify(title):
    t = (title or "").lower()
    if "quantum" in t:
        return "Quantum"
    if re.search(r"quant(itative)?[\s,/-]*(research|analyst|strateg|model|finance|invest|risk)|research(er)?[\s,/-]*quant|\bquant\b.*(research|alpha)", t):
        return "Quant Research"
    if re.search(r"\b(trader|trading)\b", t) and "quant" in t:
        return "Quant Trading"
    if re.search(r"quant(itative)?[\s,/-]*(dev|engineer|software|tech|develop)|algo(rithm|rithmic)? (dev|trad)", t):
        return "Quant Dev"
    if re.search(r"machine learning|\bml\b|deep learning|\bai\b|artificial intelligence|data scien|applied scien|research scien|\bnlp\b|computer vision|\bllm\b|reinforcement|generative|\bresearch (intern|engineer)", t):
        return "ML"
    if re.search(r"\btrader\b|\btrading\b", t):
        return "Quant Trading"
    if "quant" in t:
        return "Quant Research"
    if re.search(r"research(er)?\b", t):
        return "Research"
    return "Other"


FIT = {"Quant Research": 5, "ML": 4, "Quantum": 5, "Quant Trading": 3, "Quant Dev": 3, "Research": 2, "Other": 0}


def us_location(locs):
    if not locs:
        return True
    for l in locs:
        s = l.strip()
        if re.search(r"united states|\busa\b|\bu\.s\.|remote", s, re.I) and not re.search(r"canada|uk|india|london|europe", s, re.I):
            return True
        m = re.search(r",\s*([A-Z]{2})\b", s)
        if m and m.group(1) in US_STATES:
            return True
        if s in ("New York", "San Francisco", "Chicago", "Boston", "Seattle", "Austin"):
            return True
    return False


def flags_for(title, degrees=None, sponsorship="", locs=None):
    f = []
    t = (title or "").lower()
    if re.search(r"\bph\.?d\b|doctora", t):
        f.append("PhD")
    if re.search(r"master'?s|\bm\.?s\.? (student|intern)|graduate (student|intern|program)", t):
        f.append("Master's")
    if degrees and not any("bachelor" in d.lower() for d in degrees):
        f.append("No bachelor's")
    if sponsorship and "citizen" in sponsorship.lower():
        f.append("US citizen only")
    if locs is not None and not us_location(locs):
        f.append("Non-US")
    return ";".join(f)


def fmt_date(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def simplify_jobs():
    out = []
    for j in getj(SIMPLIFY, 120):
        if not j.get("active") or not j.get("is_visible", True):
            continue
        terms = j.get("terms") or []
        if "Summer 2027" not in terms and "N/A" not in terms and "Fall 2026" not in terms and "Winter 2027" not in terms:
            continue
        title = j.get("title", "")
        cat = j.get("category", "")
        track = classify(title)
        if cat in ("Quant", "Quantitative Finance") and track == "Other":
            track = "Quant Research"
        if track == "Other":
            continue
        if "Summer 2027" not in terms and fmt_date(j.get("date_posted")) < "2026-07-01":
            continue
        locs = j.get("locations") or []
        fl = flags_for(title, j.get("degrees"), j.get("sponsorship", ""), locs)
        if "Non-US" in fl:
            continue
        out.append({
            "company": j["company_name"], "role": title, "track": track, "location": "; ".join(locs[:3]),
            "url": j.get("url", ""), "posted": fmt_date(j.get("date_posted")), "source": "Simplify GitHub",
            "flags": fl, "fit": FIT[track] + (2 if cat in ("Quant", "Quantitative Finance") else 0),
        })
    return out


def parse_nwft(md):
    out = []
    for sec in re.split(r"\n## ", md)[1:]:
        name = sec.split("\n", 1)[0].strip()
        loc = re.search(r"\*\*Locations\*\*:\s*(.*)", sec)
        loc = loc.group(1).strip() if loc else ""
        for m in re.finditer(r"^\|([^|\n]+)\|(.*)\|\s*$", sec, re.M):
            role = m.group(1).strip()
            if role in ("Role", "-------") or set(role) <= {"-"}:
                continue
            links = re.findall(r"\[([^\]]*)\]\(([^)]+)\)", m.group(2))
            for label, url in links:
                if "❌" in label:
                    continue
                sub = re.sub(r"[✅\s]+", " ", label).strip()
                full = {"QR": "Quantitative Research Intern", "QT": "Quantitative Trading Intern",
                        "QD": "Quantitative Developer Intern", "SWE": "Software Engineer Intern",
                        "HW": "Hardware/FPGA Intern"}.get(role, role)
                if sub:
                    full += f" ({sub})"
                track = {"QR": "Quant Research", "QT": "Quant Trading", "QD": "Quant Dev"}.get(role)
                if not track:
                    continue
                out.append({"company": name, "role": full, "track": track, "location": loc, "url": url,
                            "source": "NU Fintech GitHub", "fit": FIT[track] + 1})
    return out


def nwft_jobs():
    return parse_nwft(get(NWFT).decode("utf-8", "replace"))


def readme_repo_jobs(repo):
    md = None
    for br in ("dev", "main", "master"):
        try:
            md = get(f"https://raw.githubusercontent.com/{repo}/{br}/README.md", 30).decode("utf-8", "replace")
            break
        except Exception:
            continue
    if not md:
        return []
    out = []
    last_company = ""
    for line in md.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0].lower() in ("company", "name"):
            continue
        comp = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cells[0]).replace("**", "").strip()
        comp = re.sub(r"<[^>]+>", "", comp)
        if comp in ("↳", "") and last_company:
            comp = last_company
        last_company = comp
        role = re.sub(r"<[^>]+>|\[([^\]]*)\]\([^)]*\)", r"\1", cells[1])
        loc = re.sub(r"<[^>]+>", ", ", cells[2]).strip(", ")
        link = re.search(r'href="([^"]+)"|\]\((http[^)]+)\)', cells[3])
        url = (link.group(1) or link.group(2)) if link else ""
        if "🔒" in line or not url:
            continue
        track = classify(role)
        if track == "Other":
            continue
        locs = [x.strip() for x in loc.split(",")]
        if not us_location([loc]) and not us_location(locs):
            continue
        out.append({"company": comp, "role": role, "track": track, "location": loc[:80], "url": url,
                    "source": f"GitHub {repo.split('/')[0]}", "flags": flags_for(role), "fit": FIT[track]})
    return out


def intern_ok(title):
    t = (title or "").lower()
    if "intern" not in t and "co-op" not in t and "coop" not in t:
        return False
    if "2027" in t:
        return True
    if re.search(r"202[0-6]", t):
        return False
    return True


def ats_jobs():
    out = []

    def gh(tok):
        try:
            d = getj(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs", 25)
        except Exception:
            return []
        r = []
        for j in d.get("jobs", []):
            if not intern_ok(j.get("title")):
                continue
            track = classify(j["title"])
            if track == "Other":
                continue
            loc = (j.get("location") or {}).get("name", "")
            if not us_location([loc]):
                continue
            r.append({"company": tok, "role": j["title"], "track": track, "location": loc, "url": j.get("absolute_url", ""),
                      "posted": (j.get("updated_at") or "")[:10], "source": "Greenhouse", "flags": flags_for(j["title"]),
                      "fit": FIT[track], "_tok": tok})
        return r

    def lv(tok):
        try:
            d = getj(f"https://api.lever.co/v0/postings/{tok}?mode=json", 30)
        except Exception:
            return []
        r = []
        for j in d:
            if not intern_ok(j.get("text")):
                continue
            track = classify(j["text"])
            if track == "Other":
                continue
            loc = (j.get("categories") or {}).get("location", "") or ""
            if loc and not us_location([loc]):
                continue
            r.append({"company": tok, "role": j["text"], "track": track, "location": loc, "url": j.get("hostedUrl", ""),
                      "posted": fmt_date((j.get("createdAt") or 0) / 1000), "source": "Lever",
                      "flags": flags_for(j["text"]), "fit": FIT[track], "_tok": tok})
        return r

    def ab(tok):
        try:
            d = getj(f"https://api.ashbyhq.com/posting-api/job-board/{tok}", 30)
        except Exception:
            return []
        r = []
        for j in d.get("jobs", []):
            if not intern_ok(j.get("title")):
                continue
            track = classify(j["title"])
            if track == "Other":
                continue
            loc = j.get("location") or ""
            if loc and not us_location([loc]) and not j.get("isRemote"):
                continue
            r.append({"company": tok, "role": j["title"], "track": track, "location": loc, "url": j.get("jobUrl", ""),
                      "posted": (j.get("publishedAt") or "")[:10], "source": "Ashby", "flags": flags_for(j["title"]),
                      "fit": FIT[track], "_tok": tok})
        return r

    tasks = [(gh, t) for t in dict.fromkeys(GREENHOUSE)] + [(lv, t) for t in dict.fromkeys(LEVER)] + [(ab, t) for t in dict.fromkeys(ASHBY)]
    with ThreadPoolExecutor(12) as ex:
        for res in ex.map(lambda p: p[0](p[1]), tasks):
            out.extend(res)
    return out


PRETTY = {"togetherai": "Together AI", "janestreet": "Jane Street", "hudsonrivertrading": "Hudson River Trading",
          "jumptrading": "Jump Trading", "twosigma": "Two Sigma", "akunacapital": "Akuna Capital", "drweng": "DRW",
          "scaleai": "Scale AI", "aquaticcapitalmanagement": "Aquatic Capital Management", "arrowstreetcapital": "Arrowstreet Capital",
          "chicagotradingcompany": "Chicago Trading Company", "belvederetrading": "Belvedere Trading", "ansatzcapital": "Ansatz Capital",
          "openai": "OpenAI", "cerebrassystems": "Cerebras", "squarepointcapital": "Squarepoint Capital", "xtxmarkets": "XTX Markets",
          "gresearch": "G-Research", "tower-research": "Tower Research Capital", "psiquantum": "PsiQuantum", "ionq": "IonQ",
          "characterai": "Character.AI", "elevenlabs": "ElevenLabs", "quantco": "QuantCo", "oldmissioncapital": "Old Mission Capital",
          "flowtraders": "Flow Traders", "radixtrading": "Radix Trading", "cmegroup": "CME Group"}


def pretty_company(name):
    if name in PRETTY:
        return PRETTY[name]
    if name.islower() and " " not in name:
        return name.capitalize()
    return name


def refresh(progress=None):
    stats = {}
    fetchers = [("Simplify", simplify_jobs), ("NU Fintech", nwft_jobs)] + \
               [(r.split("/")[0], (lambda rr=r: readme_repo_jobs(rr))) for r in README_REPOS] + \
               [("ATS boards", ats_jobs)]
    new_total = 0
    for name, fn in fetchers:
        try:
            rows = fn()
        except Exception as e:
            stats[name] = f"error: {e}"
            continue
        n = 0
        for r in rows:
            r["company"] = pretty_company(r["company"])
            r.pop("_tok", None)
            if "Master's" in r.get("flags", "") or "PhD" in r.get("flags", "") or "US citizen" in r.get("flags", "") or "No bachelor" in r.get("flags", ""):
                r["status"] = "Ineligible"
            _, created = db.upsert(r)
            n += created
        stats[name] = f"{len(rows)} found, {n} new"
        new_total += n
        if progress:
            progress(name, stats[name])
    db.set_meta("jobs_refreshed", time.time())
    db.set_meta("jobs_stats", json.dumps(stats))
    return stats, new_total
