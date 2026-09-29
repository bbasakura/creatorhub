// X 未回关博主核验、最新帖求回关与 24 小时观察高效执行器
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";

const PYTHON_EXE = `"D:\\soft\\Codex\\个人品牌建设\\.venv\\Scripts\\python.exe"`;
const PYTHON_CLI = `"D:\\soft\\Codex\\个人品牌建设\\app\\platforms\\x\\unreciprocated_manager.py"`;
const STREAM_REPLIER_CLI = `"D:\\soft\\Codex\\个人品牌建设\\app\\platforms\\x\\stream_replier.py"`;

// 安全导航，遇 ERR_ABORTED 自动切换到干净标签页
async function safeNavigate(browser, tabRef, url) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await tabRef.tab.goto(url);
      await tabRef.tab.playwright.waitForLoadState({ state: "domcontentloaded" });
      await tabRef.tab.playwright.waitForTimeout(1200);
      return true;
    } catch (e) {
      if (e.message && e.message.includes("ERR_ABORTED")) {
        console.log(`ERR_ABORTED on ${url}, creating fresh tab to self-heal (${attempt + 1}/3)...`);
        try {
          const oldTab = tabRef.tab;
          const freshTab = await browser.tabs.new();
          await freshTab.goto(url);
          await freshTab.playwright.waitForLoadState({ state: "domcontentloaded" });
          await freshTab.playwright.waitForTimeout(1200);
          await oldTab.close();
          tabRef.tab = freshTab;
          return true;
        } catch (inner) {
          console.warn(`Failed fresh tab recovery: ${inner.message}`);
        }
        continue;
      }
      console.warn(`Navigation error on ${url}: ${e.message}`);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return false;
}

export async function remindConfirmedBatch(agent, count = 3, accountId = null) {
  const browser = await agent.browsers.getForUrl("https://x.com/home");
  const tabs = await browser.tabs.list();
  let tab = await browser.tabs.get(tabs[0].id);
  const tabRef = { tab };

  // 1. 获取一批已确认未回关的博主（默认3位，平稳安全）
  let pendingStr = "";
  if (count === "dynamic") {
    pendingStr = execSync(`python ${PYTHON_CLI} get_dynamic 5 24`, { encoding: "utf-8" });
  } else {
    const fetchLimit = Number.isInteger(count) ? count : 3;
    pendingStr = execSync(`python ${PYTHON_CLI} get_confirmed ${fetchLimit}`, { encoding: "utf-8" });
  }

  // 过滤控制台可能的日志前缀，精确解析 JSON
  const trimmed = pendingStr.trim();
  let targets = [];
  try {
    targets = JSON.parse(trimmed);
  } catch (_) {
    const lines = trimmed.split("\n");
    for (const line of lines) {
      const l = line.trim();
      if (l.startsWith("[")) {
        try {
          targets = JSON.parse(l);
          break;
        } catch (_) {}
      }
    }
  }

  if (!targets || targets.length === 0) {
    return { status: "empty", message: "全部未回关博主已催关完毕！" };
  }

  const results = [];

  for (let i = 0; i < targets.length; i++) {
    const target = targets[i];
    const cleanHandle = target.clean_handle;
    const profileUrl = `https://x.com/${cleanHandle}`;

    console.log(`[Reminding ${i+1}/${targets.length}] @${cleanHandle}...`);
    const navOk = await safeNavigate(browser, tabRef, profileUrl);
    if (!navOk) {
      console.warn(`Could not navigate to profile ${profileUrl}`);
      continue;
    }

    // 再次复核是否已回关 (防瞬态变化)
    const doubleCheck = await tabRef.tab.playwright.evaluate(() => {
      const bodyText = document.body.innerText || "";
      return bodyText.includes("关注了你") || bodyText.includes("Follows you");
    });

    if (doubleCheck) {
      console.log(`@${cleanHandle} has refollowed just now!`);
      execSync(`python ${PYTHON_CLI} mark_refollowed "${cleanHandle}" "${(target.nick || '').replace(/"/g, '')}"`);
      results.push({ handle: cleanHandle, status: "already_refollowed" });
      continue;
    }

    // 滚动并轮询寻找最新推文
    await tabRef.tab.playwright.evaluate(() => {
      window.scrollBy(0, 500);
    });

    const latestTweet = await tabRef.tab.playwright.evaluate(async () => {
      let articles = [];
      for (let t = 0; t < 12; t++) {
        articles = Array.from(document.querySelectorAll('article'));
        if (articles.length > 0) break;
        window.scrollBy(0, 200);
        await new Promise(r => setTimeout(r, 300));
      }
      if (articles.length === 0) return null;

      // 提取所有候选推文
      const candidates = [];
      for (const art of articles) {
        const timeEl = art.querySelector('time');
        const linkEl = timeEl ? timeEl.closest('a') : null;
        if (linkEl && linkEl.href.includes('/status/')) {
          const textEl = art.querySelector('[data-testid="tweetText"]');
          const isPinned = art.innerText.includes("已置顶") || art.innerText.includes("Pinned");
          candidates.push({
            link: linkEl.href,
            text: textEl ? textEl.innerText.slice(0, 60) : "",
            isPinned
          });
        }
      }

      if (candidates.length === 0) return null;
      // 优先选最新非置顶，如果没有则选置顶
      const nonPinned = candidates.find(c => !c.isPinned);
      return nonPinned || candidates[0];
    });

    if (!latestTweet || !latestTweet.link) {
      console.log(`No tweets found for @${cleanHandle}.`);
      execSync(`python ${PYTHON_CLI} mark_no_tweets "${cleanHandle}"`);
      results.push({ handle: cleanHandle, status: "no_tweets" });
      continue;
    }

    // 随机选用真诚求关文案
    const remindPhrases = [
      "大佬顺手回个关🤝，一起交流交流～",
      "已关注大佬，求翻牌回个关呀🔥",
      "大佬求个回关，同频路上一起搞起👍",
      "前排支持大佬，顺便蹲个回关🤝",
      "同频好友来串门啦，大佬记得回个关呀☕️",
      "关注大佬好几天了，顺手回个关并肩作战呀🔥",
    ];
    const replyText = remindPhrases[Math.floor(Math.random() * remindPhrases.length)];

    console.log(`Queueing reminder draft for @${cleanHandle}'s tweet (${latestTweet.link}): "${replyText}"`);

    if (!accountId) {
      results.push({
        handle: cleanHandle,
        status: "dry_run_requires_account_id",
        tweet: latestTweet.link,
        text: replyText
      });
      continue;
    }

    const draftPayload = [{
      authorNick: target.nick || cleanHandle,
      authorHandle: cleanHandle,
      tweetLink: latestTweet.link,
      tweetText: latestTweet.text || "",
      replyText,
    }];
    const draftFile = join(os.tmpdir(), `unreciprocated_${cleanHandle}_draft.json`);
    const queuedFile = join(os.tmpdir(), `unreciprocated_${cleanHandle}_queued.json`);
    fs.writeFileSync(draftFile, JSON.stringify(draftPayload, null, 2), "utf-8");
    execSync(`${PYTHON_EXE} ${STREAM_REPLIER_CLI} enqueue-drafts ${Number(accountId)} "${draftFile}" "${queuedFile}"`, { encoding: "utf-8" });
    const queued = JSON.parse(fs.readFileSync(queuedFile, "utf-8"));
    results.push({
      handle: cleanHandle,
      status: "draft_waiting_approval",
      tweet: latestTweet.link,
      text: replyText,
      task: queued[0] || null,
    });

    // 顺手点击回到主页，彻底清除推文页 SPA 路由锁定
    try {
      await tabRef.tab.playwright.evaluate(() => {
        const homeBtn = document.querySelector('[data-testid="AppTabBar_Home_Link"]');
        if (homeBtn) homeBtn.click();
      });
      await tabRef.tab.playwright.waitForTimeout(1500);
    } catch (_) {}

    if (i < targets.length - 1) {
      const delay = 8000 + Math.floor(Math.random() * 2000);
      console.log(`Waiting ${delay/1000}s...`);
      await tabRef.tab.playwright.waitForTimeout(delay);
    }
  }

  const summaryStr = execSync(`python ${PYTHON_CLI} summary`, { encoding: "utf-8" });
  const summary = JSON.parse(summaryStr.trim());

  return { reminded: results.length, results, summary };
}
