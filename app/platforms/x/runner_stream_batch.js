// 自动化批次执行脚本：在「为你推荐」流随机抓取、去重生成微回复并执行回复落库
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";

export async function runStreamBatch(agent, targetBatchCount = 3, accountId = null) {
  const browser = await agent.browsers.getForUrl("https://x.com/home");
  const tabs = await browser.tabs.list();
  const tab = await browser.tabs.get(tabs[0].id);

  // 1. 确保在为你推荐主页
  const cur = await tab.url();
  if (!cur.includes("/home")) {
    await tab.goto("https://x.com/home");
    await tab.playwright.waitForLoadState({ state: "domcontentloaded" });
    await tab.playwright.waitForTimeout(1500);
  }

  // 2. 随机向下滚动抓取
  const rawTweets = await tab.playwright.evaluate(async () => {
    const list = [];
    const seen = new Set();
    const scrollSteps = 6 + Math.floor(Math.random() * 4);
    for (let s = 0; s < scrollSteps; s++) {
      window.scrollBy(0, 1000 + Math.floor(Math.random() * 500));
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

        list.push({ tweetLink, authorNick, authorHandle, tweetText: tweetText.slice(0, 100) });
      }
    }
    return list;
  });

  // 3. 过滤去重与生成回复
  const tmpDir = os.tmpdir();
  const scrapedFile = join(tmpDir, "scraped_tweets.json");
  const preparedFile = join(tmpDir, "prepared_candidates.json");
  fs.writeFileSync(scrapedFile, JSON.stringify(rawTweets, null, 2), "utf-8");

  const cmd = `python "D:\\soft\\Codex\\个人品牌建设\\app\\platforms\\x\\stream_replier.py" prepare "${scrapedFile}" "${preparedFile}"`;
  execSync(cmd, { encoding: "utf-8" });

  const candidates = JSON.parse(fs.readFileSync(preparedFile, "utf-8"));

  // 4. 只入 CreatorHub 草稿队列；真实写操作只能由统一 worker 执行。
  const actualCount = Math.min(candidates.length, targetBatchCount);
  const selected = candidates.slice(0, actualCount);
  if (!accountId) {
    return { candidatesFound: candidates.length, queued: [], dryRun: true, selected };
  }
  const selectedFile = join(tmpDir, "selected_reply_drafts.json");
  const queuedFile = join(tmpDir, "queued_reply_drafts.json");
  fs.writeFileSync(selectedFile, JSON.stringify(selected, null, 2), "utf-8");
  const queueCmd = `python "D:\\soft\\Codex\\个人品牌建设\\app\\platforms\\x\\stream_replier.py" enqueue-drafts ${Number(accountId)} "${selectedFile}" "${queuedFile}"`;
  execSync(queueCmd, { encoding: "utf-8" });
  const queued = JSON.parse(fs.readFileSync(queuedFile, "utf-8"));
  return { candidatesFound: candidates.length, queued, dryRun: false };
}
