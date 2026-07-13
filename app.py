import asyncio
import json
import os
import smtplib
import re
import threading
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask, jsonify, render_template_string
from playwright.async_api import async_playwright

KEYWORDS = ["devops", "kubernetes", "terraform", "aws", "ci/cd", "docker", "eks"]
MAX_CONNECTS = int(os.environ.get("MAX_CONNECTS", 5))
SEEN_FILE = "/data/seen_jobs.json"
JOBS_FILE = "/data/jobs.json"
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
  <p class="meta">DevOps jobs with &lt; {{ max_connects }} connects &nbsp;·&nbsp; Auto-refreshes every 60s</p>
  {% if jobs %}
  <div class="grid">
    {% for job in jobs %}
    <div class="card">
      {% if job.connects != None %}
        <span class="badge">{{ job.connects }} connects</span>
      {% else %}
        <span class="badge unknown">connects unknown</span>
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


async def scrape():
    seen = set(load_json(SEEN_FILE, []))
    existing_jobs = load_json(JOBS_FILE, [])
    matches = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
        await page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        cards = await page.query_selector_all("article, section[data-test='job-tile']")
        print(f"[{datetime.now()}] Found {len(cards)} cards")
        new_seen = set(seen)

        for card in cards:
            text = (await card.inner_text()).lower()
            link_el = await card.query_selector("a[href*='/jobs/']")
            link = await link_el.get_attribute("href") if link_el else ""
            if link and not link.startswith("http"):
                link = "https://www.upwork.com" + link

            job_id = link or text[:80]
            if job_id in seen:
                continue
            new_seen.add(job_id)

            if not any(k in text for k in KEYWORDS):
                continue

            m = re.search(r'(\d+)\s+connects', text, re.IGNORECASE)
            connects = int(m.group(1)) if m else None

            if connects is None or connects < MAX_CONNECTS:
                title_el = await card.query_selector("h2, h3, [data-test='job-tile-title']")
                title = (await title_el.inner_text()).strip() if title_el else "DevOps Job"
                matches.append({
                    "title": title,
                    "link": link,
                    "connects": connects,
                    "seen_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })

        await browser.close()

    if matches:
        send_email(matches)
        all_jobs = matches + existing_jobs
        save_json(JOBS_FILE, all_jobs[:200])  # keep latest 200

    save_json(SEEN_FILE, list(new_seen)[-500:])
    print(f"[{datetime.now()}] New matches: {len(matches)}")


def run_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        try:
            loop.run_until_complete(scrape())
        except Exception as e:
            print(f"Scrape error: {e}")
        import time; time.sleep(CHECK_INTERVAL)


@app.route("/")
def index():
    jobs = load_json(JOBS_FILE, [])
    return render_template_string(HTML, jobs=jobs, max_connects=MAX_CONNECTS, interval=CHECK_INTERVAL)


@app.route("/api/jobs")
def api_jobs():
    return jsonify(load_json(JOBS_FILE, []))


if __name__ == "__main__":
    threading.Thread(target=run_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
