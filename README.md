# Intern Tracker

Local website that tracks internship applications, finds new postings, reads your Gmail for status changes, and keeps the Excel tracker in sync.

## Run

Double-click `run.bat` (or `python app.py`), then open http://127.0.0.1:5055. The first start imports `../Internship Applications Tracker.xlsx` and searches for jobs in the background (about a minute).

## Tabs

- **My tracker**: every job you applied to or decided on. Change the status dropdown inline; click a row for notes, phase, and links. Click a role name to open the posting.
- **Discover**: postings found automatically and not yet tracked. Changing a status (or adding notes) moves a job into My tracker. Filters hide firms you already applied to, ineligible roles (PhD, Master's, US citizen only, non-US), and tracks outside QR / ML / Quantum / Trading.
- **Email log**: what Gmail sync detected. Emails it could not match to a job can be assigned by hand.

## Job sources

- SimplifyJobs/Summer2027-Internships (listings.json)
- northwesternfintech/2027QuantInternships
- vanshb03/Summer2027-Internships README (ouckah and cvrve repos are tried too)
- Greenhouse, Lever, and Ashby public job-board APIs for about 130 firm boards (edit the lists at the top of `sources.py`)
- LinkedIn is not scraped (its terms forbid it and it blocks bots). The page has LinkedIn search buttons, and LinkedIn job-alert emails are a good manual source.

Press **Find new jobs** any time; it also refreshes every 6 hours while the site is running.

## Gmail sync (auto-update)

1. Google account -> Security -> turn on 2-Step Verification.
2. Google account -> Security -> App passwords -> create one named "Intern Tracker".
3. Copy `.env.example` to `.env`, put the 16-character app password in `GMAIL_APP_PASSWORD`.
4. Restart. Sync runs at start and every 15 minutes, or press **Sync Gmail**.

It scans mail from the last 45 days, files every job-related email under the Gmail label "Jobs" (change with GMAIL_LABEL in .env) and stars it, without marking anything read or deleting anything, detects application confirmations, assessment invites and completions, interviews, offers, and rejections, matches them to a firm, and moves the status forward. A rejection email always wins. Anything you edit by hand after an email arrived is not overwritten by older emails.

Applications confirmed by email for firms not in the tracker get added automatically.

## Excel and CSV sync

- Every change on the site rewrites `../Internship Applications Tracker.xlsx` (Applied, Not Applied, and a new Discovered tab with clickable links) a few seconds later, plus `jobs.csv` here. A `.bak` copy is kept. Close the workbook in Excel first or the write fails (the site shows the error).
- **Import Excel** reads the Applied and Not Applied tabs back in, so you can also edit statuses in Excel.
- Set `AUTO_EXCEL=0` in `.env` to stop automatic writes.
