// 为你推荐推文抓取与真实观点回复执行模块
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";

// 安全导航函数，处理 SPA 下 ERR_ABORTED
async function safeNavigate(tab, url) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await tab.goto(url);
      await tab.playwright.waitForLoadState({ state: "domcontentloaded" });
      await tab.playwright.waitForTimeout(1000);
      return true;
    } catch (e) {
      if (e.message && e.message.includes("ERR_ABORTED")) {
        console.log(`ERR_ABORTED encountered for ${url}, retry ${attempt + 1}...`);
        await new Promise(r => setTimeout(r, 2000));
        continue;
      }
      throw e;
    }
  }
  return false;
}

// 1. 抓取为你推荐流候选推文
export async function scrapeForYouCandidates(agent, scrollCount = 5) {
  const browser = await agent.browsers.getForUrl("https://x.com/home");
  const tabs = await browser.tabs.list();
  const tab = await browser.tabs.get(tabs[0].id);

  const cur = await tab.url();
  if (!cur.includes("/home")) {
    await safeNavigate(tab, "https://x.com/home");
    await tab.playwright.waitForTimeout(1500);
  }

  const rawTweets = await tab.playwright.evaluate(async (steps) => {
    const list = [];
    const seen = new Set();
    for (let s = 0; s < steps; s++) {
      window.scrollBy(0, 800 + Math.floor(Math.random() * 400));
      await new Promise(r => setTimeout(r, 900));

      const articles = Array.from(document.querySelectorAll('article'));
      for (const art of articles) {
        const timeEl = art.querySelector('time');
        const linkEl = timeEl ? timeEl.closest('a') : null;
        if (!linkEl || !linkEl.href.includes('/status/')) continue;
        const tweetLink = linkEl.href;
        if (seen.has(tweetLink)) continue;
        seen.add(tweetLink);

        const userEl = art.querySelector('[data-testid="User-Name"]');
        let authorNick = "";
        let authorHandle = "";
        if (userEl) {
          const text = userEl.innerText || "";
          const parts = text.split("\n");
          authorNick = parts[0] || "";
          authorHandle = parts.find(p => p.startsWith("@")) || "";
        }

        const textEl = art.querySelector('[data-testid="tweetText"]');
        const tweetText = textEl ? textEl.innerText : "";

        // 仅抓取有实质内容的推文
        if (tweetText.trim().length > 5) {
          list.push({ tweetLink, authorNick, authorHandle, tweetText: tweetText.trim() });
        }
      }
    }
    return list;
  }, scrollCount);

  // 通过 Python 过滤
  const tmpDir = os.tmpdir();
  const scrapedFile = join(tmpDir, "scraped_raw.json");
  const filteredFile = join(tmpDir, "scraped_filtered.json");
  fs.writeFileSync(scrapedFile, JSON.stringify(rawTweets, null, 2), "utf-8");

  const cmd = `python "D:\\soft\\Codex\\个人品牌建设\\app\\platforms\\x\\stream_replier.py" filter "${scrapedFile}" "${filteredFile}"`;
  execSync(cmd, { encoding: "utf-8" });

  const filtered = JSON.parse(fs.readFileSync(filteredFile, "utf-8"));
  return filtered;
}

// 2. 兼容旧入口，但不再直接写 X；候选统一进入 CreatorHub durable draft 队列。
export async function executeRealReplies(agent, replyTasks, accountId = null) {
  const tmpDir = os.tmpdir();
  const selected = Array.isArray(replyTasks) ? replyTasks : [];
  if (!accountId) {
    return { queued: [], dryRun: true, selected };
  }
  const selectedFile = join(tmpDir, "legacy_real_reply_drafts.json");
  const queuedFile = join(tmpDir, "legacy_real_reply_queued.json");
  fs.writeFileSync(selectedFile, JSON.stringify(selected, null, 2), "utf-8");
  const queueCmd = `python "D:\\soft\\Codex\\个人品牌建设\\app\\platforms\\x\\stream_replier.py" enqueue-drafts ${Number(accountId)} "${selectedFile}" "${queuedFile}"`;
  execSync(queueCmd, { encoding: "utf-8" });
  const queued = JSON.parse(fs.readFileSync(queuedFile, "utf-8"));
  return { queued, dryRun: false };
}
