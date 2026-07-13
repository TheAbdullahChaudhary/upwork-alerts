import asyncio
import json
import os
import smtplib
import re
import threading
import requests
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask, jsonify, render_template_string

KEYWORDS = ["devops", "kubernetes", "terraform", "aws", "ci/cd", "docker", "eks"]
MAX_PROPOSALS = int(os.environ.get("MAX_PROPOSALS", 5))
SEEN_FILE = "/data/seen_jobs.json"
JOBS_FILE = "/data/jobs.json"
COOKIES_FILE = "/cookies/cookies.json"
SEARCH_URL = "https://www.upwork.com/nx/search/jobs/?q=devops&sort=recency"
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", 120))

app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Upwork Job Alerts</title>
  <meta http-equiv="refresh" content="60">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; background: #0d1117; color: #e6edf3; padding: 24px; }
    h1 { color: #14a800; margin-bottom: 8px; }
    .meta { color: #8b949e; font-size: 13px; margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
    .card h3 { font-size: 15px; margin-bottom: 8px; }
    .card a { color: #58a6ff; text-decoration: none; font-size: 13px; }
    .card a:hover { text-decoration: underline; }
    .badge { display: inline-block; background: #14a800; color: #fff; border-radius: 4px;
             font-size: 12px; padding: 2px 8px; margin-bottom: 8px; }
    .badge.unknown { background: #6e7681; }
    .time { color: #8b949e; font-size: 11px; margin-top: 8px; }
    .empty { color: #8b949e; text-align: center; padding: 60px; }
  </style>
</head>
<body>
  <h1>🚀 Upwork Job Alerts</h1>
  <p class="meta">DevOps jobs with &lt; {{ max_proposals }} proposals &nbsp;·&nbsp; Auto-refreshes every 60s</p>
  {% if jobs %}
  <div class="grid">
    {% for job in jobs %}
    <div class="card">
      {% if job.proposals != None %}
        <span class="badge" style="background:#0077b6">{{ job.proposals }} proposals</span>
      {% else %}
        <span class="badge unknown">proposals unknown</span>
      {% endif %}
      <h3>{{ job.title }}</h3>
      <a href="{{ job.link }}" target="_blank">View on Upwork →</a>
      <p class="time">{{ job.seen_at }}</p>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <p class="empty">No matching jobs found yet. Checking every {{ interval }}s...</p>
  {% endif %}
</body>
</html>"""


def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs("/data", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def send_email(jobs):
    body = "\n\n".join(
        f"Title: {j['title']}\nConnects: {j['connects']}\nURL: {j['link']}"
        for j in jobs
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Upwork Alert: {len(jobs)} new DevOps job(s)"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print(f"Email sent: {len(jobs)} jobs")
    except Exception as e:
        print(f"Email error: {e}")


def load_cookies():
    if not os.path.exists(COOKIES_FILE):
        return {}
    with open(COOKIES_FILE) as f:
        raw = json.load(f)
    return {c["name"]: c["value"] for c in raw}


def scrape():
    seen = set(load_json(SEEN_FILE, []))
    existing_jobs = load_json(JOBS_FILE, [])
    matches = []
    new_seen = set(seen)

    cookies = load_cookies()
    xsrf = cookies.get("XSRF-TOKEN", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "X-Upwork-Accept-Language": "en-US",
        "Referer": "https://www.upwork.com/nx/search/jobs/",
        "X-XSRF-TOKEN": xsrf,
    }

    params = {
        "q": "devops",
        "sort": "recency",
        "paging": "0;50",
    }

    try:
        resp = requests.get(
            "https://www.upwork.com/search/jobs/url",
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=20
        )
        print(f"[{datetime.now()}] API status: {resp.status_code}")

        if resp.status_code != 200:
            # fallback: try the jobs search API
            resp = requests.get(
                "https://www.upwork.com/ab/jobs/search/",
                params=params,
                headers=headers,
                cookies=cookies,
                timeout=20
            )
            print(f"[{datetime.now()}] Fallback status: {resp.status_code}")

        data = resp.json()
        jobs_list = data.get("results", data.get("jobs", []))
        print(f"[{datetime.now()}] Found {len(jobs_list)} jobs from API")

    except Exception as e:
        print(f"[{datetime.now()}] API error: {e}")
        jobs_list = []

    for job in jobs_list:
        job_id = job.get("id") or job.get("uid") or str(job)[:80]
        if job_id in seen:
            continue
        new_seen.add(job_id)

        title = job.get("title", "DevOps Job")
        if not any(k in title.lower() for k in KEYWORDS):
            continue

        proposals = job.get("proposals_count") or job.get("proposalsTier") or None
        if isinstance(proposals, str):
            m = re.search(r'\d+', proposals)
            proposals = int(m.group()) if m else None

        if proposals is None or proposals < MAX_PROPOSALS:
            cid = job.get("ciphertext") or job.get("id", "")
            link = f"https://www.upwork.com/jobs/{cid}" if cid else "https://www.upwork.com/nx/search/jobs/?q=devops"
            matches.append({
                "title": title,
                "link": link,
                "proposals": proposals,
                "seen_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            })

    if matches:
        send_email(matches)
        save_json(JOBS_FILE, (matches + existing_jobs)[:200])

    save_json(SEEN_FILE, list(new_seen)[-500:])
    print(f"[{datetime.now()}] New matches: {len(matches)}")


def run_loop():
    while True:
        try:
            scrape()
        except Exception as e:
            print(f"Scrape error: {e}")
        import time; time.sleep(CHECK_INTERVAL)


@app.route("/")
def index():
    jobs = load_json(JOBS_FILE, [])
    return render_template_string(HTML, jobs=jobs, max_proposals=MAX_PROPOSALS, interval=CHECK_INTERVAL)


@app.route("/api/jobs")
def api_jobs():
    return jsonify(load_json(JOBS_FILE, []))


if __name__ == "__main__":
    threading.Thread(target=run_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
