import asyncio
import json
import os
import smtplib
import re
from email.mime.text import MIMEText
from playwright.async_api import async_playwright

KEYWORDS = ["devops", "kubernetes", "terraform", "aws", "ci/cd", "docker", "eks"]
MAX_CONNECTS = 5
SEEN_FILE = "/data/seen_jobs.json"
SEARCH_URL = "https://www.upwork.com/nx/search/jobs/?q=devops&sort=recency"

SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
NOTIFY_EMAIL = os.environ["NOTIFY_EMAIL"]


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    os.makedirs("/data", exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-500:], f)


def send_email(jobs):
    body = "\n\n".join(
        f"Title: {j['title']}\nConnects: {j['connects']}\nURL: {j['link']}"
        for j in jobs
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Upwork Alert: {len(jobs)} new DevOps job(s)"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    print(f"Email sent: {len(jobs)} jobs")


async def scrape_jobs():
    seen = load_seen()
    matches = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
        await page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        cards = await page.query_selector_all("article, section[data-test='job-tile']")
        print(f"Found {len(cards)} job cards")

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

            connects_match = re.search(r'(\d+)\s+connects', text, re.IGNORECASE)
            connects = int(connects_match.group(1)) if connects_match else None

            if connects is None or connects < MAX_CONNECTS:
                title_el = await card.query_selector("h2, h3, [data-test='job-tile-title']")
                title = (await title_el.inner_text()).strip() if title_el else "DevOps Job"
                connects_label = f"{connects}" if connects is not None else "unknown"
                matches.append({"title": title, "link": link, "connects": connects_label})
                print(f"Match: {title} | connects: {connects_label}")

        save_seen(new_seen)
        await browser.close()

    if matches:
        send_email(matches)
    else:
        print("No new matching jobs.")


async def main():
    interval = 120
    print(f"Starting monitor (every {interval}s)...")
    while True:
        try:
            await scrape_jobs()
        except Exception as e:
            print(f"Error: {e}")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
