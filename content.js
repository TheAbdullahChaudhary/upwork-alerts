// Runs inside upwork.com — reads job cards and sends matches to background
const KEYWORDS = ["devops", "kubernetes", "terraform", "aws", "ci/cd", "docker", "eks"];
const MAX_CONNECTS = 5;
const CHECK_INTERVAL_MS = 60_000; // re-scan every 60s (for SPA navigation)

function getJobCards() {
  // Upwork job card selectors (works on /nx/search/jobs/ and feed pages)
  return document.querySelectorAll('[data-test="job-tile-list"] section, .job-tile, article[data-ev-job-uid]');
}

function extractConnects(card) {
  const text = card.innerText || "";
  const match = text.match(/(\d+)\s+Connects/i);
  return match ? parseInt(match[1]) : null;
}

function extractJobId(card) {
  return card.getAttribute("data-ev-job-uid") ||
    card.querySelector("a[href*='/jobs/']")?.href ||
    null;
}

function isDevOpsJob(card) {
  const text = (card.innerText || "").toLowerCase();
  return KEYWORDS.some(k => text.includes(k));
}

function scanJobs() {
  const cards = getJobCards();
  if (!cards.length) return;

  chrome.storage.local.get(["seenJobs"], ({ seenJobs = [] }) => {
    const seen = new Set(seenJobs);
    const newSeen = [...seen];
    const matches = [];

    cards.forEach(card => {
      const id = extractJobId(card);
      if (!id || seen.has(id)) return;

      newSeen.push(id);
      const connects = extractConnects(card);
      const isMatch = isDevOpsJob(card) && (connects === null || connects < MAX_CONNECTS);

      if (isMatch) {
        const title = card.querySelector("h2, h3, [data-test='job-tile-title']")?.innerText?.trim() || "New Job";
        const link = card.querySelector("a[href*='/jobs/']")?.href || window.location.href;
        matches.push({ title, link, connects });
      }
    });

    if (matches.length) {
      chrome.runtime.sendMessage({ type: "NEW_JOBS", jobs: matches });
    }

    chrome.storage.local.set({ seenJobs: newSeen.slice(-500) }); // keep last 500
  });
}

// Initial scan + periodic re-scan for SPA navigation
scanJobs();
setInterval(scanJobs, CHECK_INTERVAL_MS);

// Also scan on URL change (Upwork is a SPA)
let lastUrl = location.href;
new MutationObserver(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    setTimeout(scanJobs, 2000); // wait for content to load
  }
}).observe(document.body, { childList: true, subtree: true });
