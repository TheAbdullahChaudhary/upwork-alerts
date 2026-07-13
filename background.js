// background.js — handles notifications and periodic tab refresh

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== "NEW_JOBS") return;

  msg.jobs.forEach(job => {
    const connects = job.connects !== null ? `${job.connects} connects` : "connects unknown";
    chrome.notifications.create(job.link, {
      type: "basic",
      iconUrl: "icon.png",
      title: `Upwork: ${connects}`,
      message: job.title,
      priority: 2,
      buttons: [{ title: "Open Job" }]
    });
  });
});

// Open job on notification button click
chrome.notifications.onButtonClicked.addListener((notifId) => {
  chrome.tabs.create({ url: notifId });
});

chrome.notifications.onClicked.addListener((notifId) => {
  chrome.tabs.create({ url: notifId });
});

// Auto-refresh Upwork job search tab every 2 minutes to catch new jobs
chrome.alarms.create("refresh", { periodInMinutes: 2 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "refresh") return;

  const [tab] = await chrome.tabs.query({ url: "https://www.upwork.com/*" });
  if (tab) {
    chrome.tabs.reload(tab.id);
  } else {
    // Open the search page if no Upwork tab is open
    chrome.tabs.create({
      url: "https://www.upwork.com/nx/search/jobs/?q=devops&sort=recency",
      active: false
    });
  }
});
