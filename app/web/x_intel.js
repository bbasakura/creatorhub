"use strict";

let X_INTEL_BENCHMARKS = [];
let X_INTEL_RADAR = [];
let X_INTEL_BLACK_HORSES = [];
let X_INTEL_AUTOMATION = null;
let X_INTEL_ALERTS = [];
let X_INTEL_DAILY_BRIEFS = [];
let X_INTEL_OPPORTUNITIES = [];
let X_INTEL_SCAN = null;
let X_GROWTH_DASHBOARD = null;

function xIntelAccountId() {
  return Number($("x-intel-acc") && $("x-intel-acc").value || 0);
}

function xIntelEnsureAccountOptions() {
  const select = $("x-intel-acc");
  if (!select) return 0;
  const previous = select.value;
  const rows = (ACCOUNTS || []).filter(function(a) {
    return a.platform === "x" && a.status !== "invalid";
  });
  select.innerHTML = rows.map(function(a) {
    const handle = String(a.sec_uid || a.nickname || ("x-" + a.id)).replace(/^@/, "");
    return '<option value="' + Number(a.id) + '">@' + esc(handle) + '</option>';
  }).join("");
  if (previous && rows.some(function(a) { return String(a.id) === previous; })) {
    select.value = previous;
  } else if (rows.length) {
    select.value = String(rows[0].id);
  }
  if (select._csSync) select._csSync();
  return Number(select.value || 0);
}

function xIntelDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    hour12: false
  });
}

function xGrowthWindowCell(row, hours) {
  const value = row && row.windows && row.windows[String(hours)];
  if (!value || !value.available) return '<span class="mut">待积累</span>';
  return '<b>' + fmtNum(value.views || 0) + '</b><small class="mut" style="display:block">' +
    Number(value.age_hours || hours).toFixed(1) + 'h 快照</small>';
}

function renderXGrowthDashboard() {
  const data = X_GROWTH_DASHBOARD;
  const revenue = data && data.revenue || {};
  const account = data && data.account || {};
  const lifecycle = data && data.lifecycle || { items: [] };
  const attribution = data && data.attribution || { items: [] };
  const growth = data && data.growth || { points: [] };
  const official = data && data.creator_studio || {};

  if ($("x-growth-followers")) $("x-growth-followers").textContent = data ? fmtNum(account.followers || 0) : "—";
  if ($("x-growth-verified-progress")) {
    $("x-growth-verified-progress").textContent = data
      ? fmtNum(revenue.official_verified_followers || 0) + " / " + fmtNum(revenue.target_verified_followers || 500)
      : "—";
  }
  if ($("x-growth-impression-progress")) {
    $("x-growth-impression-progress").textContent = data
      ? fmtNum(revenue.official_qualified_impressions_90d || 0) + " / " + fmtNum(revenue.target_qualified_impressions_90d || 500000)
      : "—";
  }
  if ($("x-growth-public-impressions")) {
    $("x-growth-public-impressions").textContent = data
      ? fmtNum(official.analytics_ok ? official.impressions || 0 : revenue.public_impressions_90d_reference || 0)
      : "—";
  }
  if ($("x-growth-median-views")) $("x-growth-median-views").textContent = data ? fmtNum(Math.round(lifecycle.median_views_30d || 0)) : "—";
  if ($("x-growth-snapshots")) $("x-growth-snapshots").textContent = data ? fmtNum(growth.snapshot_count || 0) : "—";

  renderXRevenueQualificationPreview();
  if ($("x-growth-scope") && data) {
    const source = revenue.official_source === "x_creator_studio" ? "X Creator Studio 官方" : "本地兜底";
    $("x-growth-scope").textContent =
      (revenue.note_scope || "") + " 当前资格数据来源：" + source +
      (revenue.official_synced_at ? "；最后同步 " + xIntelDate(revenue.official_synced_at + (String(revenue.official_synced_at).endsWith("Z") ? "" : "Z")) : "") + "。";
  }

  const officialFields = {
    "x-official-impressions": official.impressions,
    "x-official-engagements": official.engagements,
    "x-official-profile-visits": official.profile_visits,
    "x-official-replies": official.replies,
    "x-official-likes": official.likes,
    "x-official-reposts": official.reposts,
    "x-official-bookmarks": official.bookmarks,
    "x-official-shares": official.shares,
    "x-official-net-follows": official.net_follows,
  };
  Object.keys(officialFields).forEach(function(id) {
    if ($(id)) $(id).textContent = official.analytics_ok ? fmtNum(officialFields[id] || 0) : "—";
  });
  if ($("x-official-engagement-rate")) {
    $("x-official-engagement-rate").textContent = official.analytics_ok
      ? (Number(official.engagement_rate || 0) * 100).toFixed(2) + "%"
      : "—";
  }
  const officialBadge = $("x-growth-official-source");
  if (officialBadge) {
    officialBadge.textContent = official.analytics_ok ? "X 官方" : "未同步";
    officialBadge.className = "pill " + (official.analytics_ok ? "done" : "invalid");
  }
  if ($("x-official-analytics-scope")) {
    $("x-official-analytics-scope").textContent = official.available
      ? "来源：X Creator Studio · Account Analytics / Original Content Rewards；最后同步 " +
        xIntelDate(String(official.captured_at || "") + (String(official.captured_at || "").endsWith("Z") ? "" : "Z")) +
        "。认证粉丝 " + fmtNum(official.verified_followers || 0) + " / " + fmtNum(official.follower_count || 0) +
        "；90 天合格曝光 " + fmtNum(official.qualified_impressions_90d || 0) + "。"
      : "尚未同步 X Creator Studio 官方数据。";
  }
  const officialDaily = $("x-official-daily-table");
  if (officialDaily) {
    const rows = Array.isArray(official.daily) ? official.daily : [];
    officialDaily.innerHTML = rows.length ? rows.map(function(row) {
      return '<tr>' +
        '<td>' + esc(row.date || "") + '</td>' +
        '<td class="num"><b>' + fmtNum(row.impressions || 0) + '</b></td>' +
        '<td class="num">' + fmtNum(row.verified_impressions || 0) + '</td>' +
        '<td class="num">' + fmtNum(row.engagements || 0) + '</td>' +
        '<td class="num">' + fmtNum(row.profile_visits || 0) + '</td>' +
        '<td class="num">' + fmtNum(row.replies || 0) + '</td>' +
        '<td class="num">' + fmtNum(row.likes || 0) + '</td>' +
        '<td class="num">+' + fmtNum(row.follows || 0) + '</td>' +
        '<td class="num">-' + fmtNum(row.unfollows || 0) + '</td>' +
      '</tr>';
    }).join("") : empty(9, "暂无 X 官方分析数据", "i-eye", "点击“同步 X 官方数据”读取 Creator Studio");
  }

  const lifeBody = $("x-growth-lifecycle-table");
  if (lifeBody) {
    const rows = Array.isArray(lifecycle.items) ? lifecycle.items : [];
    lifeBody.innerHTML = rows.length ? rows.map(function(row) {
      const created = row.create_time ? new Date(Number(row.create_time) * 1000).toLocaleString("zh-CN") : "—";
      return '<tr>' +
        '<td class="wrap" style="min-width:260px;max-width:430px"><b>' + esc(String(row.text || "（无正文）").slice(0, 120)) + '</b><small class="mut" style="display:block">' + esc(created) + ' · 快照 ' + fmtNum(row.snapshot_count || 0) + '</small></td>' +
        '<td class="num"><b>' + fmtNum(row.views || 0) + '</b><small class="mut" style="display:block">' + fmtNum(row.likes || 0) + '赞 · ' + fmtNum(row.replies || 0) + '回复</small></td>' +
        '<td><span class="pill">' + esc(row.classification || "积累中") + '</span></td>' +
        '<td>' + xGrowthWindowCell(row, 1) + '</td>' +
        '<td>' + xGrowthWindowCell(row, 3) + '</td>' +
        '<td>' + xGrowthWindowCell(row, 6) + '</td>' +
        '<td>' + xGrowthWindowCell(row, 24) + '</td>' +
        '<td>' + xGrowthWindowCell(row, 72) + '</td>' +
        '<td class="num">' + (Number(row.engagement_rate || 0) * 100).toFixed(2) + '%</td>' +
      '</tr>';
    }).join("") : empty(9, "生命周期数据正在积累", "i-bolt", "点“我的作品 → 同步作品”后开始保存帖子指标快照");
  }
  if ($("x-growth-lifecycle-note")) $("x-growth-lifecycle-note").textContent = lifecycle.note || "生命周期快照正在积累。";

  const attributionBody = $("x-growth-attribution-table");
  if (attributionBody) {
    const rows = Array.isArray(attribution.items) ? attribution.items : [];
    attributionBody.innerHTML = rows.length ? rows.map(function(row) {
      return '<tr>' +
        '<td class="wrap" style="min-width:300px;max-width:560px"><b>' + esc(String(row.text || "（无正文）").slice(0, 150)) + '</b></td>' +
        '<td class="num"><b>+' + Number(row.estimated_followers || 0).toFixed(1) + '</b></td>' +
        '<td class="num">' + fmtNum(row.attributed_view_delta || 0) + '</td>' +
        '<td class="num">' + fmtNum(row.intervals || 0) + '</td>' +
      '</tr>';
    }).join("") : empty(4, "涨粉归因数据正在积累", "i-user", "需要至少两个账号增长快照，并且期间有帖子曝光增长");
  }
  if ($("x-growth-attribution-note")) $("x-growth-attribution-note").textContent = attribution.note || "涨粉归因为估算值。";
}

async function refreshXGrowthDashboard(showToast) {
  const accountId = xIntelAccountId() || xIntelEnsureAccountOptions();
  if (!accountId) {
    X_GROWTH_DASHBOARD = null;
    renderXGrowthDashboard();
    return;
  }
  try {
    X_GROWTH_DASHBOARD = await api("/api/x/growth-dashboard?account_id=" + accountId);
    renderXGrowthDashboard();
    if (showToast) toast("X 增长与收益驾驶舱已刷新", "ok");
  } catch (error) {
    if (showToast) toast("驾驶舱加载失败：" + error.message, "err", 7000);
  }
}

async function syncXCreatorStudioOfficial() {
  const accountId = xIntelAccountId() || xIntelEnsureAccountOptions();
  if (!accountId) {
    toast("请先选择 X 账号", "err");
    return;
  }
  const button = $("x-growth-official-sync-btn");
  await withBusy(button, "同步官方数据中", async function() {
    try {
      X_GROWTH_DASHBOARD = await api(
        "/api/x/growth-dashboard/official-sync?account_id=" + accountId,
        { method: "POST" }
      );
      renderXGrowthDashboard();
      const official = X_GROWTH_DASHBOARD.creator_studio || {};
      toast(
        "X 官方数据已同步：认证粉丝 " + fmtNum(official.verified_followers || 0) +
        "，7天曝光 " + fmtNum(official.impressions || 0) +
        "，90天合格曝光 " + fmtNum(official.qualified_impressions_90d || 0),
        "ok",
        8000
      );
    } catch (error) {
      toast("同步 X Creator Studio 失败：" + error.message, "err", 8500);
    }
  });
}

function setXRevenueQualificationCard(cardId, statusId, fillId, passed, statusText, progress) {
  const card = $(cardId);
  const status = $(statusId);
  const fill = $(fillId);
  if (card) card.classList.toggle("done", !!passed);
  if (status) status.textContent = statusText;
  if (fill) fill.style.width = Math.max(0, Math.min(100, Number(progress || 0))) + "%";
}

function renderXRevenueQualificationPreview() {
  const revenue = X_GROWTH_DASHBOARD && X_GROWTH_DASHBOARD.revenue || {};
  const official = X_GROWTH_DASHBOARD && X_GROWTH_DASHBOARD.creator_studio || {};
  const premium = true;
  const identity = true;
  const enrolled = !!revenue.rewards_enrolled;
  const verified = Number(revenue.official_verified_followers || official.verified_followers || 0);
  const verifiedTarget = Math.max(1, Number(revenue.target_verified_followers || 500));
  const impressions = Number(revenue.official_qualified_impressions_90d || official.qualified_impressions_90d || 0);
  const impressionsTarget = Math.max(1, Number(revenue.target_qualified_impressions_90d || 500000));
  const verifiedPct = Math.min(100, verified * 100 / verifiedTarget);
  const impressionsPct = Math.min(100, impressions * 100 / impressionsTarget);

  setXRevenueQualificationCard(
    "x-qual-premium", "x-qual-premium-status", "x-qual-premium-fill",
    premium, premium ? "已开通" : "未开通", premium ? 100 : 0
  );
  setXRevenueQualificationCard(
    "x-qual-identity", "x-qual-identity-status", "x-qual-identity-fill",
    identity, identity ? "已完成" : "未完成", identity ? 100 : 0
  );
  setXRevenueQualificationCard(
    "x-qual-enrolled", "x-qual-enrolled-status", "x-qual-enrolled-fill",
    enrolled, enrolled ? "已加入" : "未加入", enrolled ? 100 : 0
  );
  setXRevenueQualificationCard(
    "x-qual-verified", "x-qual-verified-status", "x-qual-verified-fill",
    verified >= verifiedTarget,
    fmtNum(verified) + " / " + fmtNum(verifiedTarget),
    verifiedPct
  );
  setXRevenueQualificationCard(
    "x-qual-impressions", "x-qual-impressions-status", "x-qual-impressions-fill",
    impressions >= impressionsTarget,
    fmtNum(impressions) + " / " + fmtNum(impressionsTarget),
    impressionsPct
  );
  if ($("x-qual-verified-pct")) {
    $("x-qual-verified-pct").textContent = verifiedPct.toFixed(verifiedPct >= 10 ? 0 : 2) + "%";
  }
  if ($("x-qual-impressions-pct")) {
    $("x-qual-impressions-pct").textContent = impressionsPct.toFixed(impressionsPct >= 10 ? 1 : 2) + "%";
  }
}

function xIntelVerified(verified) {
  return verified
    ? '<span title="X 蓝V认证" aria-label="X 蓝V认证" style="color:#1d9bf0;font-weight:900">✓</span>'
    : "";
}

function xIntelAvatar(row) {
  if (!row.avatar) return '<span style="width:34px;height:34px;border-radius:50%;display:grid;place-items:center;background:var(--surface-2)">' + ic("i-user") + '</span>';
  return '<img src="' + esc(row.avatar) + '" alt="" referrerpolicy="no-referrer" style="width:34px;height:34px;border-radius:50%;object-fit:cover">';
}

function renderXIntelBenchmarks() {
  const body = $("x-intel-benchmark-table");
  if (!body) return;
  if ($("x-intel-kpi-bench")) $("x-intel-kpi-bench").textContent = fmtNum(X_INTEL_BENCHMARKS.length);
  if (!X_INTEL_BENCHMARKS.length) {
    body.innerHTML = empty(7, "还没有对标账号", "i-user", "先添加几个你想长期观察的 X 账号");
    return;
  }
  body.innerHTML = X_INTEL_BENCHMARKS.map(function(row) {
    const error = row.last_error
      ? '<small style="color:var(--danger);display:block" title="' + esc(row.last_error) + '">最近读取失败</small>'
      : "";
    return '<tr>' +
      '<td><div style="display:flex;gap:9px;align-items:center">' + xIntelAvatar(row) +
        '<div><b>' + esc(row.nickname || row.handle) + ' ' + xIntelVerified(row.verified) + '</b>' +
        '<small class="mut" style="display:block">@' + esc(row.handle) + '</small>' + error + '</div></div></td>' +
      '<td class="num">' + fmtNum(row.follower_count || 0) + '</td>' +
      '<td class="num">' + fmtNum(row.tweet_count || 0) + '</td>' +
      '<td class="wrap" style="max-width:220px">' + esc(row.note || "—") + '</td>' +
      '<td><span class="pill ' + (row.enabled ? "done" : "invalid") + '">' + (row.enabled ? "启用" : "停用") + '</span></td>' +
      '<td class="mut">' + xIntelDate(row.last_synced_at) + '</td>' +
      '<td class="acttd">' +
        '<button class="ghost sm" onclick="refreshXIntelBenchmark(' + Number(row.id) + ')">刷新</button>' +
        '<button class="ghost sm" onclick="editXIntelBenchmark(' + Number(row.id) + ')">备注</button>' +
        '<button class="ghost sm" onclick="toggleXIntelBenchmark(' + Number(row.id) + ',' + (row.enabled ? "false" : "true") + ')">' + (row.enabled ? "停用" : "启用") + '</button>' +
        '<button class="ghost sm danger" onclick="deleteXIntelBenchmark(' + Number(row.id) + ')">' + ic("i-trash") + '删除</button>' +
      '</td></tr>';
  }).join("");
}

function xIntelTrend(row, hours) {
  const trends = row && row.trends || {};
  return trends[String(hours)] || { available: false };
}

function xIntelTrendSpeed(row, hours) {
  const trend = xIntelTrend(row, hours);
  return trend.available ? Number(trend.views_per_hour || 0) : -Infinity;
}

function xIntelTrendText(row, hours) {
  const trend = xIntelTrend(row, hours);
  if (!trend.available) return '<span class="mut">' + hours + 'h 待积累</span>';
  const delta = Number(trend.view_delta || 0);
  const speed = Number(trend.views_per_hour || 0);
  const pct = trend.view_growth_pct === null || trend.view_growth_pct === undefined
    ? ""
    : " · " + Number(trend.view_growth_pct).toFixed(1) + "%";
  const sign = delta > 0 ? "+" : "";
  return '<span><b>' + hours + 'h ' + sign + fmtNum(delta) + '</b><small class="mut" style="display:block">' +
    sign + fmtNum(Math.round(speed)) + '/h' + pct + '</small></span>';
}

function xIntelSortedRows() {
  const query = String($("x-intel-search") && $("x-intel-search").value || "").trim().toLowerCase();
  const sort = String($("x-intel-sort") && $("x-intel-sort").value || "score");
  const num = function(value) { return Number(value || 0); };
  const rows = X_INTEL_RADAR.filter(function(row) {
    if (!query) return true;
    return [row.author_handle, row.author_name, row.text].some(function(value) {
      return String(value || "").toLowerCase().includes(query);
    });
  });
  rows.sort(function(a, b) {
    if (sort === "views") return num(b.view_count) - num(a.view_count);
    if (sort === "efficiency") return num(b.exposure_efficiency) - num(a.exposure_efficiency);
    if (sort === "engagement") return num(b.engagement_rate) - num(a.engagement_rate);
    if (sort === "growth3") return xIntelTrendSpeed(b, 3) - xIntelTrendSpeed(a, 3);
    if (sort === "growth6") return xIntelTrendSpeed(b, 6) - xIntelTrendSpeed(a, 6);
    if (sort === "growth24") return xIntelTrendSpeed(b, 24) - xIntelTrendSpeed(a, 24);
    if (sort === "time") return new Date(b.posted_at || 0) - new Date(a.posted_at || 0);
    return num(b.radar_score) - num(a.radar_score);
  });
  return rows;
}

function renderXIntelRadar() {
  const body = $("x-intel-radar-table");
  if (!body) return;
  const rows = xIntelSortedRows();
  if ($("x-intel-result-count")) {
    $("x-intel-result-count").textContent = "显示 " + rows.length + " / 本轮 " + X_INTEL_RADAR.length;
  }
  if (!rows.length) {
    body.innerHTML = empty(8, X_INTEL_RADAR.length ? "当前筛选没有结果" : "暂无雷达结果", "i-bolt", "添加对标账号后点「扫描对标账号」");
    return;
  }
  body.innerHTML = rows.map(function(row, index) {
    const views = Number(row.view_count || 0);
    const likes = Number(row.like_count || 0);
    const replies = Number(row.reply_count || 0);
    const retweets = Number(row.retweet_count || 0);
    const interactions = likes + replies + retweets;
    const rate = Number(row.engagement_rate || 0) * 100;
    const efficiency = Number(row.exposure_efficiency || 0);
    const score = Number(row.radar_score || 0);
    return '<tr>' +
      '<td class="num"><b>' + (index + 1) + '</b></td>' +
      '<td><b>' + esc(row.author_name || row.author_handle) + ' ' + xIntelVerified(row.author_verified) + '</b>' +
        '<small class="mut" style="display:block">@' + esc(row.author_handle) + ' · ' + fmtNum(row.author_followers || 0) + ' 粉</small></td>' +
      '<td class="wrap" style="min-width:280px;max-width:520px"><div style="line-height:1.55">' + esc(row.text || "（无正文）") + '</div>' +
        '<small class="mut">' + xIntelDate(row.posted_at) + '</small></td>' +
      '<td><b>' + fmtNum(views) + ' 曝光</b><small class="mut" style="display:block">' +
        fmtNum(likes) + '赞 · ' + fmtNum(replies) + '回复 · ' + fmtNum(retweets) + '转发 · 互动 ' + fmtNum(interactions) + '</small></td>' +
      '<td style="min-width:150px"><div style="display:grid;gap:4px">' +
        xIntelTrendText(row, 3) + xIntelTrendText(row, 6) + xIntelTrendText(row, 24) + '</div></td>' +
      '<td><b>' + efficiency.toFixed(1) + '×</b><small class="mut" style="display:block">互动率 ' + rate.toFixed(2) + '%</small></td>' +
      '<td class="num"><b>' + score.toFixed(1) + '</b></td>' +
      '<td class="acttd">' +
        '<button class="ghost sm" onclick="openXIntelPost(' + Number(row.id) + ')">原帖</button>' +
        '<button class="ghost sm" onclick="draftXIntelReply(' + Number(row.id) + ')">回复草稿</button>' +
      '</td></tr>';
  }).join("");
}

function renderXIntelBlackHorses() {
  const body = $("x-intel-blackhorse-table");
  if (!body) return;
  if (!X_INTEL_BLACK_HORSES.length) {
    body.innerHTML = empty(9, X_INTEL_SCAN ? "本轮没有符合粉丝上限的候选黑马" : "暂无黑马数据", "i-target", "先完成一次对标账号扫描");
    return;
  }
  body.innerHTML = X_INTEL_BLACK_HORSES.map(function(row, index) {
    const growth = row.best_growth && row.best_growth.available
      ? row.best_growth.window_hours + 'h +' + fmtNum(row.best_growth.view_delta || 0) +
        ' · ' + fmtNum(Math.round(row.best_growth.views_per_hour || 0)) + '/h'
      : "待积累";
    return '<tr>' +
      '<td class="num"><b>' + (index + 1) + '</b></td>' +
      '<td><b>' + esc(row.name || row.handle) + ' ' + xIntelVerified(row.verified) + '</b><small class="mut" style="display:block">@' + esc(row.handle) + '</small></td>' +
      '<td class="num">' + fmtNum(row.followers || 0) + '</td>' +
      '<td class="num">' + fmtNum(row.post_count || 0) + ' 条</td>' +
      '<td class="num"><b>' + fmtNum(row.avg_views || 0) + '</b><small class="mut" style="display:block">最高 ' + fmtNum(row.max_views || 0) + '</small></td>' +
      '<td class="num"><b>' + Number(row.avg_efficiency || 0).toFixed(1) + '×</b><small class="mut" style="display:block">最高 ' + Number(row.max_efficiency || 0).toFixed(1) + '×</small></td>' +
      '<td>' + esc(growth) + '</td>' +
      '<td class="num"><b>' + Number(row.black_horse_score || 0).toFixed(1) + '</b></td>' +
      '<td class="wrap" style="max-width:320px">' + esc(row.reason || "") + '</td>' +
    '</tr>';
  }).join("");
}

function renderXIntelDigest() {
  const box = $("x-intel-digest");
  if (!box) return;
  const digest = X_INTEL_SCAN && X_INTEL_SCAN.digest;
  if (!digest) {
    box.className = "hint";
    box.innerHTML = X_INTEL_SCAN
      ? "本轮扫描还没有情报总结。点击「生成总结」。"
      : "完成一次扫描后，可以生成本轮情报总结。AI 未配置或调用失败时会自动使用规则摘要。";
    return;
  }
  const source = X_INTEL_SCAN.summary_source === "model" ? "AI" : "规则回退";
  const list = function(title, rows, field, detail) {
    const values = Array.isArray(rows) ? rows : [];
    if (!values.length) return "";
    return '<div style="margin-top:12px"><b>' + esc(title) + '</b><div style="display:grid;gap:8px;margin-top:7px">' +
      values.map(function(item) {
        return '<div class="hint" style="margin:0"><b>' + esc(item[field] || "") + '</b>' +
          (item[detail] ? '<div class="mut" style="margin-top:3px">' + esc(item[detail]) + '</div>' : '') + '</div>';
      }).join("") + '</div></div>';
  };
  const warnings = Array.isArray(digest.watchouts) && digest.watchouts.length
    ? '<div style="margin-top:12px"><b>数据提醒</b><div class="mut" style="margin-top:6px">' +
      digest.watchouts.map(function(x) { return '• ' + esc(x); }).join("<br>") + '</div></div>'
    : "";
  box.className = "";
  box.innerHTML =
    '<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">' +
      '<div><h3 style="margin:0 0 6px">' + esc(digest.headline || "本轮情报总结") + '</h3>' +
      '<div class="mut" style="line-height:1.65">' + esc(digest.overview || "") + '</div></div>' +
      '<span class="pill done">' + esc(source) + '</span>' +
    '</div>' +
    list("值得关注的主题", digest.topics, "title", "why") +
    list("内容机会", digest.opportunities, "angle", "why") +
    list("继续观察", digest.watchlist, "handle", "reason") +
    warnings +
    '<small class="mut" style="display:block;margin-top:10px">生成时间：' + xIntelDate(X_INTEL_SCAN.summary_generated_at) + '</small>';
}

function renderXIntelOpportunities() {
  const body = $("x-intel-opportunity-table");
  if (!body) return;
  const rows = Array.isArray(X_INTEL_OPPORTUNITIES) ? X_INTEL_OPPORTUNITIES : [];
  if (!rows.length) {
    body.innerHTML = empty(7, "暂无内容机会", "i-send", "完成情报扫描后点“生成机会 + 草稿”，或开启自动选题草稿");
    return;
  }
  body.innerHTML = rows.map(function(row) {
    const sourceCount = Array.isArray(row.source_tweet_ids) ? row.source_tweet_ids.length : 0;
    const sourceLabel = row.generation_source === "model" ? "AI 原创" : "规则生成";
    return '<tr>' +
      '<td class="num"><b>' + Number(row.score || 0).toFixed(1) + '</b></td>' +
      '<td class="wrap" style="min-width:240px;max-width:390px"><b>' + esc(row.topic || "内容机会") + '</b>' +
        '<div class="mut" style="margin-top:5px;line-height:1.55">' + esc(row.angle || "") + '</div>' +
        '<small class="mut" style="display:block;margin-top:5px">' + esc(row.content_type || "观点短帖") + ' · ' + esc(sourceLabel) + '</small></td>' +
      '<td class="wrap" style="max-width:320px">' + esc(row.why_now || "") + '</td>' +
      '<td class="wrap" style="max-width:320px">' + esc(row.strategy || "") + '</td>' +
      '<td class="wrap" style="min-width:300px;max-width:460px"><div style="white-space:pre-wrap;line-height:1.55">' + esc(row.draft_text || "") + '</div>' +
        (row.draft_task_id ? '<small class="mut" style="display:block;margin-top:6px">发布草稿 #' + Number(row.draft_task_id) + '</small>' : '') + '</td>' +
      '<td><b>' + fmtNum(sourceCount) + ' 条</b>' +
        (sourceCount ? '<button class="ghost sm" style="display:block;margin-top:6px" onclick="openXIntelOpportunitySource(' + Number(row.id) + ')">查看证据</button>' : '') + '</td>' +
      '<td><span class="pill done">待确认</span>' +
        (row.draft_task_id ? '<button class="ghost sm" style="display:block;margin-top:6px" onclick="openXIntelDraftQueue()">任务队列</button>' : '') + '</td>' +
    '</tr>';
  }).join("");
}

function openXIntelOpportunitySource(id) {
  const row = X_INTEL_OPPORTUNITIES.find(function(item) { return Number(item.id) === Number(id); });
  const urls = row && Array.isArray(row.source_urls) ? row.source_urls : [];
  if (urls.length) window.open(urls[0], "_blank", "noopener");
}

function openXIntelDraftQueue() {
  if (typeof switchTab === "function") switchTab("queue", true);
}

async function generateXIntelOpportunities() {
  const accountId = xIntelAccountId();
  if (!accountId) {
    toast("请先选择 X 账号", "err");
    return;
  }
  if (!X_INTEL_SCAN || !X_INTEL_SCAN.id) {
    toast("请先完成一次 X 情报扫描", "err");
    return;
  }
  const count = Math.max(1, Math.min(6, Number($("x-intel-opportunity-count") && $("x-intel-opportunity-count").value || 3)));
  const button = $("x-intel-opportunity-generate");
  await withBusy(button, "生成中", async function() {
    try {
      const result = await api("/api/x/intel/opportunities/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: accountId,
          scan_id: Number(X_INTEL_SCAN.id),
          count: count
        })
      });
      X_INTEL_OPPORTUNITIES = Array.isArray(result.items) ? result.items : [];
      renderXIntelOpportunities();
      toast(result.message || ("已生成 " + X_INTEL_OPPORTUNITIES.length + " 条待确认草稿"), "ok", 7000);
    } catch (error) {
      toast("生成内容机会失败：" + error.message, "err", 7500);
    }
  });
}

function renderXIntelAutomation() {
  const data = X_INTEL_AUTOMATION || {};
  const cfg = data.config || {};
  const schedule = data.schedule || {};
  const setValue = function(id, value) {
    const el = $(id);
    if (el && document.activeElement !== el) el.value = String(value);
  };
  setValue("x-intel-auto-enabled", cfg.enabled ? 1 : 0);
  setValue("x-intel-auto-interval", cfg.interval_hours || 3);
  setValue("x-intel-auto-posts", cfg.posts_per_account || 5);
  setValue("x-intel-auto-brief", cfg.daily_brief_enabled === false ? 0 : 1);
  setValue("x-intel-auto-brief-hour", cfg.daily_brief_hour === undefined ? 20 : cfg.daily_brief_hour);
  setValue("x-intel-auto-opportunities", cfg.auto_opportunities_enabled ? 1 : 0);
  setValue("x-intel-auto-draft-count", cfg.auto_draft_count || 3);
  setValue("x-intel-auto-speed", cfg.explosion_min_views_per_hour || 300);
  setValue("x-intel-auto-delta", cfg.explosion_min_view_delta || 800);
  setValue("x-intel-auto-efficiency", cfg.explosion_min_efficiency === undefined ? 0.5 : cfg.explosion_min_efficiency);
  setValue("x-intel-auto-notify-explosion", cfg.notify_explosions === false ? 0 : 1);
  setValue("x-intel-auto-notify-brief", cfg.notify_daily_brief === false ? 0 : 1);

  const badge = $("x-intel-auto-status");
  if (badge) {
    badge.textContent = cfg.enabled ? (schedule.running ? "扫描中" : "已开启") : "未开启";
    badge.className = "pill " + (cfg.enabled ? "done" : "invalid");
  }
  const meta = $("x-intel-auto-meta");
  if (meta) {
    if (!cfg.enabled) {
      meta.textContent = "当前关闭，不会自动访问 X。开启后 scheduler 每分钟只检查是否到点，真正读取按采样间隔执行。";
    } else {
      meta.textContent =
        "上次采样 " + xIntelDate(schedule.last_scan_at) +
        " · 下次约 " + xIntelDate(schedule.next_scan_at) +
        " · 每 " + Number(cfg.interval_hours || 3) + " 小时采样" +
        " · 日报 " + String(Number(cfg.daily_brief_hour || 20)).padStart(2, "0") + ":00（账号时区）" +
        (cfg.auto_opportunities_enabled ? " · 每轮自动生成 " + Number(cfg.auto_draft_count || 3) + " 条待确认草稿" : " · 自动选题草稿关闭");
    }
  }
}

function renderXIntelAlerts() {
  const body = $("x-intel-alert-table");
  if (!body) return;
  if (!X_INTEL_ALERTS.length) {
    body.innerHTML = empty(8, "暂无起爆信号", "i-bolt", "需要先积累真实3h/6h/24h快照，并达到你设置的增速阈值");
    return;
  }
  const levelText = { hot: "强起爆", exploding: "起爆", rising: "抬升" };
  body.innerHTML = X_INTEL_ALERTS.map(function(row) {
    return '<tr>' +
      '<td class="mut">' + xIntelDate(row.created_at) + '</td>' +
      '<td><span class="pill done">' + esc(levelText[row.level] || row.level || "信号") + '</span></td>' +
      '<td><b>' + esc(row.author_name || row.author_handle) + '</b><small class="mut" style="display:block">@' + esc(row.author_handle || "") + '</small></td>' +
      '<td><b>' + Number(row.window_hours || 0) + 'h +' + fmtNum(row.view_delta || 0) + '</b><small class="mut" style="display:block">' + fmtNum(Math.round(row.views_per_hour || 0)) + '/h</small></td>' +
      '<td class="num">' + Number(row.exposure_efficiency || 0).toFixed(2) + '×</td>' +
      '<td class="wrap" style="max-width:340px">' + esc(row.reason || "") + '</td>' +
      '<td>' + (row.notified_at ? '<span class="pill done">已推送</span>' : '<span class="mut">页面记录</span>') + '</td>' +
      '<td class="acttd"><button class="ghost sm" onclick="openXIntelAlert(' + Number(row.id) + ')">原帖</button></td>' +
    '</tr>';
  }).join("");
}

function renderXIntelDailyBriefs() {
  const box = $("x-intel-daily-brief-list");
  if (!box) return;
  if (!X_INTEL_DAILY_BRIEFS.length) {
    box.innerHTML = '<div class="hint">暂无每日简报。自动情报开启后，到达设定的账号本地时间会基于最近一次有效扫描生成。</div>';
    return;
  }
  box.innerHTML = X_INTEL_DAILY_BRIEFS.map(function(row) {
    const summary = row.summary || {};
    const topics = Array.isArray(summary.topics) ? summary.topics : [];
    const watchlist = Array.isArray(summary.watchlist) ? summary.watchlist : [];
    const source = row.summary_source === "model" ? "AI" : "规则回退";
    return '<div class="hint" style="margin:0">' +
      '<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">' +
        '<div><b>' + esc(row.local_date || "") + ' · ' + esc(summary.headline || "X 情报日报") + '</b>' +
        '<div class="mut" style="margin-top:5px;line-height:1.6">' + esc(summary.overview || "") + '</div></div>' +
        '<span class="pill done">' + esc(source) + '</span>' +
      '</div>' +
      (topics.length ? '<div style="margin-top:8px"><b>值得看：</b>' + topics.slice(0, 3).map(function(item) { return esc(item.title || ""); }).join(" / ") + '</div>' : '') +
      (watchlist.length ? '<div style="margin-top:5px"><b>继续观察：</b>' + watchlist.slice(0, 3).map(function(item) { return '@' + esc(String(item.handle || "").replace(/^@/, "")); }).join(" / ") + '</div>' : '') +
      '<small class="mut" style="display:block;margin-top:7px">起爆信号 ' + fmtNum(row.alert_count || 0) +
      ' 条 · ' + (row.notified_at ? "已推送" : "未推送") + ' · 生成 ' + xIntelDate(row.generated_at) + '</small>' +
    '</div>';
  }).join("");
}

async function refreshXIntelAutomationPanels() {
  if (PLATFORM !== "x") return;
  const accountId = xIntelAccountId();
  if (!accountId) return;
  try {
    const result = await Promise.all([
      api("/api/x/intel/automation?account_id=" + accountId),
      api("/api/x/intel/alerts?account_id=" + accountId + "&limit=30"),
      api("/api/x/intel/daily-briefs?account_id=" + accountId + "&limit=7"),
      api("/api/x/intel/opportunities?account_id=" + accountId + "&limit=30")
    ]);
    X_INTEL_AUTOMATION = result[0] || null;
    X_INTEL_ALERTS = Array.isArray(result[1].items) ? result[1].items : [];
    X_INTEL_DAILY_BRIEFS = Array.isArray(result[2].items) ? result[2].items : [];
    X_INTEL_OPPORTUNITIES = Array.isArray(result[3].items) ? result[3].items : [];
    renderXIntelAutomation();
    renderXIntelAlerts();
    renderXIntelDailyBriefs();
    renderXIntelOpportunities();
  } catch (error) {
    toast("自动情报状态加载失败：" + error.message, "err", 6500);
  }
}

async function saveXIntelAutomation() {
  const accountId = xIntelAccountId();
  if (!accountId) {
    toast("请先选择 X 账号", "err");
    return;
  }
  const old = X_INTEL_AUTOMATION && X_INTEL_AUTOMATION.config || {};
  const button = $("x-intel-auto-save");
  await withBusy(button, "保存中", async function() {
    try {
      const result = await api("/api/x/intel/automation", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: accountId,
          enabled: String($("x-intel-auto-enabled").value) === "1",
          interval_hours: Number($("x-intel-auto-interval").value || 3),
          posts_per_account: Number($("x-intel-auto-posts").value || 5),
          max_accounts: Number(old.max_accounts || 30),
          daily_brief_enabled: String($("x-intel-auto-brief").value) === "1",
          daily_brief_hour: Number($("x-intel-auto-brief-hour").value || 20),
          notify_explosions: String($("x-intel-auto-notify-explosion").value) === "1",
          notify_daily_brief: String($("x-intel-auto-notify-brief").value) === "1",
          auto_opportunities_enabled: String($("x-intel-auto-opportunities").value) === "1",
          auto_draft_count: Math.max(1, Math.min(6, Number($("x-intel-auto-draft-count").value || 3))),
          explosion_min_views_per_hour: Math.max(1, Number($("x-intel-auto-speed").value || 300)),
          explosion_min_view_delta: Math.max(1, Number($("x-intel-auto-delta").value || 800)),
          explosion_min_efficiency: Math.max(0, Number($("x-intel-auto-efficiency").value || 0.5)),
          explosion_min_engagement_rate: Number(old.explosion_min_engagement_rate === undefined ? 0.02 : old.explosion_min_engagement_rate)
        })
      });
      X_INTEL_AUTOMATION = result;
      renderXIntelAutomation();
      toast(result.config && result.config.enabled ? "自动情报已开启" : "自动情报设置已保存", "ok");
    } catch (error) {
      toast("保存自动情报失败：" + error.message, "err", 7000);
    }
  });
}

function openXIntelAlert(id) {
  const row = X_INTEL_ALERTS.find(function(item) { return Number(item.id) === Number(id); });
  if (row && row.tweet_url) window.open(row.tweet_url, "_blank", "noopener");
}

function renderXIntelMeta() {
  const scan = X_INTEL_SCAN;
  if ($("x-intel-kpi-coverage")) $("x-intel-kpi-coverage").textContent = scan ? Number(scan.coverage || 0).toFixed(1) + "%" : "—";
  if ($("x-intel-kpi-posts")) $("x-intel-kpi-posts").textContent = fmtNum(scan && scan.post_count || 0);
  if ($("x-intel-kpi-failed")) $("x-intel-kpi-failed").textContent = fmtNum(scan && scan.failed_accounts || 0);
  const scope = $("x-intel-scope");
  if (!scope) return;
  if (!scan) {
    scope.textContent = "这里不是全 X 榜单。雷达只扫描你启用的对标账号及其最近原创帖，并明确显示本轮覆盖率。";
    return;
  }
  scope.textContent =
    "扫描 " + scan.requested_accounts + " 个对标账号 · 成功 " + scan.successful_accounts +
    " · 失败 " + scan.failed_accounts + " · 覆盖率 " + Number(scan.coverage || 0).toFixed(1) +
    "% · 每号最近 " + scan.posts_per_account + " 条原创帖 · 本轮 " + scan.post_count +
    " 条 · " + xIntelDate(scan.finished_at);
}

async function refreshXIntel() {
  if (PLATFORM !== "x") return;
  const accountId = xIntelEnsureAccountOptions();
  if (!accountId) {
    X_INTEL_BENCHMARKS = [];
    X_INTEL_RADAR = [];
    X_INTEL_BLACK_HORSES = [];
    X_INTEL_AUTOMATION = null;
    X_INTEL_ALERTS = [];
    X_INTEL_DAILY_BRIEFS = [];
    X_INTEL_OPPORTUNITIES = [];
    X_INTEL_SCAN = null;
    X_GROWTH_DASHBOARD = null;
    renderXGrowthDashboard();
    renderXIntelBenchmarks();
    renderXIntelRadar();
    renderXIntelBlackHorses();
    renderXIntelDigest();
    renderXIntelAutomation();
    renderXIntelAlerts();
    renderXIntelDailyBriefs();
    renderXIntelOpportunities();
    renderXIntelMeta();
    return;
  }
  try {
    const maxFollowers = Number($("x-intel-blackhorse-max") && $("x-intel-blackhorse-max").value || 50000);
    const result = await Promise.all([
      api("/api/x/intel/benchmarks?account_id=" + accountId),
      api("/api/x/intel/radar?account_id=" + accountId),
      api("/api/x/intel/black-horses?account_id=" + accountId + "&max_followers=" + maxFollowers + "&limit=20"),
      api("/api/x/growth-dashboard?account_id=" + accountId)
    ]);
    X_INTEL_BENCHMARKS = Array.isArray(result[0]) ? result[0] : [];
    X_INTEL_RADAR = Array.isArray(result[1].items) ? result[1].items : [];
    X_INTEL_SCAN = result[1].scan || null;
    X_INTEL_BLACK_HORSES = Array.isArray(result[2].items) ? result[2].items : [];
    X_GROWTH_DASHBOARD = result[3] || null;
    renderXGrowthDashboard();
    if ($("x-intel-blackhorse-note") && result[2].definition) {
      $("x-intel-blackhorse-note").textContent = result[2].definition;
    }
    renderXIntelBenchmarks();
    renderXIntelRadar();
    renderXIntelBlackHorses();
    renderXIntelDigest();
    renderXIntelMeta();
    await refreshXIntelAutomationPanels();
  } catch (error) {
    toast("X 情报加载失败：" + error.message, "err", 6500);
  }
}

async function refreshXIntelBlackHorses() {
  const accountId = xIntelAccountId();
  if (!accountId) return;
  const maxFollowers = Number($("x-intel-blackhorse-max") && $("x-intel-blackhorse-max").value || 50000);
  try {
    const result = await api("/api/x/intel/black-horses?account_id=" + accountId + "&max_followers=" + maxFollowers + "&limit=20");
    X_INTEL_BLACK_HORSES = Array.isArray(result.items) ? result.items : [];
    if ($("x-intel-blackhorse-note") && result.definition) {
      $("x-intel-blackhorse-note").textContent = result.definition;
    }
    renderXIntelBlackHorses();
  } catch (error) {
    toast("黑马数据加载失败：" + error.message, "err", 6500);
  }
}

async function generateXIntelDigest(force) {
  const accountId = xIntelAccountId();
  if (!accountId || !X_INTEL_SCAN || !X_INTEL_SCAN.id) {
    toast("请先完成一次 X 情报扫描", "err");
    return;
  }
  const maxFollowers = Number($("x-intel-blackhorse-max") && $("x-intel-blackhorse-max").value || 50000);
  const button = force ? $("x-intel-digest-refresh-btn") : $("x-intel-digest-btn");
  await withBusy(button, force ? "重新分析中" : "分析中", async function() {
    try {
      const result = await api("/api/x/intel/digest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: accountId,
          scan_id: Number(X_INTEL_SCAN.id),
          force: !!force,
          max_followers: maxFollowers
        })
      });
      X_INTEL_SCAN = result.scan || X_INTEL_SCAN;
      renderXIntelDigest();
      toast(
        X_INTEL_SCAN.summary_source === "model"
          ? "AI 情报总结已生成"
          : "情报总结已生成（当前使用规则回退）",
        "ok",
        6500
      );
    } catch (error) {
      toast("生成情报总结失败：" + error.message, "err", 7000);
    }
  });
}

async function addXIntelBenchmark() {
  const accountId = xIntelAccountId();
  const handle = String($("x-intel-handle") && $("x-intel-handle").value || "").trim();
  const note = String($("x-intel-note") && $("x-intel-note").value || "").trim();
  if (!accountId) {
    toast("请先选择 X 读取账号", "err");
    return;
  }
  if (!handle) {
    toast("请输入 X handle", "err");
    return;
  }
  const button = evtBtn();
  await withBusy(button, "读取资料中", async function() {
    try {
      await api("/api/x/intel/benchmarks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId, handle: handle, note: note })
      });
      $("x-intel-handle").value = "";
      $("x-intel-note").value = "";
      toast("已加入对标账号池", "ok");
      await refreshXIntel();
    } catch (error) {
      toast("添加失败：" + error.message, "err", 6500);
    }
  });
}

async function toggleXIntelBenchmark(id, enabled) {
  try {
    await api("/api/x/intel/benchmarks/" + id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: enabled })
    });
    await refreshXIntel();
  } catch (error) {
    toast("更新失败：" + error.message, "err");
  }
}

async function editXIntelBenchmark(id) {
  const row = X_INTEL_BENCHMARKS.find(function(item) { return Number(item.id) === Number(id); });
  if (!row) return;
  const note = await uiPrompt({
    title: "编辑 @" + row.handle + " 备注",
    hint: "可以写赛道、语言区或你关注它的原因",
    value: row.note || ""
  });
  if (note === null) return;
  try {
    await api("/api/x/intel/benchmarks/" + id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: note.trim() })
    });
    await refreshXIntel();
  } catch (error) {
    toast("更新备注失败：" + error.message, "err");
  }
}

async function refreshXIntelBenchmark(id) {
  const button = evtBtn();
  await withBusy(button, "刷新中", async function() {
    try {
      await api("/api/x/intel/benchmarks/" + id + "/refresh", { method: "POST" });
      toast("账号资料已刷新", "ok");
      await refreshXIntel();
    } catch (error) {
      toast("刷新失败：" + error.message, "err", 6500);
    }
  });
}

async function deleteXIntelBenchmark(id) {
  const row = X_INTEL_BENCHMARKS.find(function(item) { return Number(item.id) === Number(id); });
  const confirmed = await uiConfirm({
    title: "移出对标账号",
    message: "确认移出 @" + (row && row.handle || id) + "？历史扫描快照会保留。",
    okText: "移出",
    danger: true
  });
  if (!confirmed) return;
  try {
    await api("/api/x/intel/benchmarks/" + id, { method: "DELETE" });
    toast("已移出对标账号池", "ok");
    await refreshXIntel();
  } catch (error) {
    toast("删除失败：" + error.message, "err");
  }
}

async function scanXIntel() {
  const accountId = xIntelAccountId();
  if (!accountId) {
    toast("请先选择 X 读取账号", "err");
    return;
  }
  const postsPerAccount = Number($("x-intel-posts-per-account") && $("x-intel-posts-per-account").value || 5);
  const button = $("x-intel-scan-btn");
  await withBusy(button, "扫描中", async function() {
    try {
      const result = await api("/api/x/intel/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: accountId,
          posts_per_account: postsPerAccount,
          max_accounts: 30
        })
      });
      X_INTEL_SCAN = result.scan || null;
      X_INTEL_RADAR = Array.isArray(result.items) ? result.items : [];
      const success = X_INTEL_SCAN && X_INTEL_SCAN.successful_accounts || 0;
      const requested = X_INTEL_SCAN && X_INTEL_SCAN.requested_accounts || 0;
      const failed = X_INTEL_SCAN && X_INTEL_SCAN.failed_accounts || 0;
      toast(
        "扫描完成：" + success + "/" + requested + " 个账号，" + X_INTEL_RADAR.length + " 条帖子",
        failed ? "warn" : "ok",
        7000
      );
      await refreshXIntel();
    } catch (error) {
      toast("X 情报扫描失败：" + error.message, "err", 8000);
    }
  });
}

function openXIntelPost(id) {
  const row = X_INTEL_RADAR.find(function(item) { return Number(item.id) === Number(id); });
  const url = row && (row.tweet_url || (row.tweet_id ? "https://x.com/i/web/status/" + row.tweet_id : ""));
  if (url) window.open(url, "_blank", "noopener");
}

async function draftXIntelReply(id) {
  const row = X_INTEL_RADAR.find(function(item) { return Number(item.id) === Number(id); });
  const accountId = xIntelAccountId();
  if (!row || !accountId) return;
  try {
    const preview = await api("/api/x/reply/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        account_id: accountId,
        text: row.text || " ",
        author_handle: row.author_handle || "",
        threshold: 4,
        use_ai: true
      })
    });
    if (!preview.eligible || !preview.reply) {
      toast("这条帖子当前不适合自动生成回复：" + (preview.reason || "未通过回复判断"), "info", 7000);
      return;
    }
    const confirmed = await uiConfirm({
      title: "生成回复草稿",
      message:
        "@" + row.author_handle + "\n\n原帖：" + String(row.text || "").slice(0, 180) +
        "\n\n建议回复：" + preview.reply + "\n\n只生成草稿，不会直接发送。",
      okText: "生成草稿"
    });
    if (!confirmed) return;
    const result = await api("/api/x/reply/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        account_id: accountId,
        tweet_ref: row.tweet_url || row.tweet_id,
        text: String(preview.reply).slice(0, 280),
        author_handle: row.author_handle || "",
        source_text: row.text || ""
      })
    });
    toast("回复草稿已创建 #" + (result.task_id || "") + "，可到任务队列审核", "ok", 6500);
  } catch (error) {
    toast("生成回复草稿失败：" + error.message, "err", 7000);
  }
}

Object.assign(window, {
  refreshXIntel: refreshXIntel,
  refreshXGrowthDashboard: refreshXGrowthDashboard,
  syncXCreatorStudioOfficial: syncXCreatorStudioOfficial,
  renderXRevenueQualificationPreview: renderXRevenueQualificationPreview,
  addXIntelBenchmark: addXIntelBenchmark,
  toggleXIntelBenchmark: toggleXIntelBenchmark,
  editXIntelBenchmark: editXIntelBenchmark,
  refreshXIntelBenchmark: refreshXIntelBenchmark,
  deleteXIntelBenchmark: deleteXIntelBenchmark,
  scanXIntel: scanXIntel,
  renderXIntelRadar: renderXIntelRadar,
  renderXIntelBlackHorses: renderXIntelBlackHorses,
  refreshXIntelBlackHorses: refreshXIntelBlackHorses,
  generateXIntelDigest: generateXIntelDigest,
  generateXIntelOpportunities: generateXIntelOpportunities,
  renderXIntelOpportunities: renderXIntelOpportunities,
  openXIntelOpportunitySource: openXIntelOpportunitySource,
  openXIntelDraftQueue: openXIntelDraftQueue,
  refreshXIntelAutomationPanels: refreshXIntelAutomationPanels,
  saveXIntelAutomation: saveXIntelAutomation,
  openXIntelAlert: openXIntelAlert,
  openXIntelPost: openXIntelPost,
  draftXIntelReply: draftXIntelReply
});

if (CURRENT_TAB === "x-intel" && PLATFORM === "x") {
  setTimeout(refreshXIntel, 250);
}

setInterval(function() {
  if (CURRENT_TAB === "x-intel" && PLATFORM === "x") {
    refreshXIntelAutomationPanels();
  }
}, 60000);
