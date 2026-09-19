'use strict';

/**
 * 688 航线 · 交互层 v2
 * 任务制：每站拆成可执行任务卡（做法+教程+装备三位一体）
 * 原地展开面板 / 任务级勾选（localStorage）/ 八站全通发勋章
 */
(function () {
  var TASK_KEY = 'yz-voyage-tasks';
  var BADGE_KEY = 'yz-voyage-badge';
  var TOTAL = 8;

  /* ── 资源构造器 ── */
  function post(href, label) { return { kind: 'post', href: href, label: label }; }
  function tool(href, label) { return { kind: 'tool', href: href, label: label }; }
  function shop(href, label) { return { kind: 'shop', href: href, label: label }; }
  function gear(href, label, code, codeLabel) { return { kind: 'gear', href: href, label: label, code: code, codeLabel: codeLabel }; }
  function wip(label) { return { kind: 'wip', label: label }; }

  /* ── 八站任务表（做法、教程、装备强关联）── */
  var STATIONS = {
    1: { ico: '🌐', name: '通网', k: 'STATION 01 · 起锚', tasks: [
      { title: '装好电脑端代理客户端', how: 'Mac / Windows 都用 Clash Verge（免费开源）。先把官方安装包装上、导入订阅跑通，再谈优化。',
        res: [gear('https://github.com/clash-verge-rev/clash-verge-rev/releases', 'Clash Verge 官方下载（免费）'), post('../posts/chuhai-infra.html', '八层清单 · 网络篇')] },
      { title: '手机端也要能上', how: 'iPhone 需要美区 Apple ID 下载 Shadowrocket（约 $2.99，第 2 站会教你搞定美区 ID）；安卓装 Clash Meta。',
        res: [gear('https://apps.apple.com/us/app/shadowrocket/id932747118', 'Shadowrocket（美区 App Store）')] },
      { title: '订一条稳定的主线路', how: '选运营三年以上的服务商，先月付测稳定性再上年付。重要业务永远别挂免费节点。',
        res: [wip('鱼总在用的线路 · 整理中，先 X 私信问我')] },
      { title: '关键业务配静态 IP', how: '批量注册、长期养号要用静态住宅 IP，并且一个 IP 只养一套账号，别交叉污染。',
        res: [wip('静态 IP 渠道推荐 · 整理中')] }
    ]},
    2: { ico: '📡', name: '立号', k: 'STATION 02 · 通讯湾', tasks: [
      { title: '注册一个海外邮箱', how: 'Gmail 首选：挂美国或新加坡节点注册，资料如实填，恢复邮箱和手机号都绑上——它是你所有海外账号的根。',
        res: [] },
      { title: '搞定海外 Apple ID', how: '免费自己注册美区 ID，千万别买号（随时被找回）。国区微信不用弃，双 ID 切换用。',
        res: [wip('美区 Apple ID 保姆级教程 · 整理中')] },
      { title: '拿一个能长期保号的海外号码', how: '图省事直接买我的 ENC 现货（真实 +1 号码，当天发）；想要英区选 Giffgaff。先看五档排行搞清自己要哪档。',
        res: [shop('../shop/enc-tmobile/', 'ENC 美国卡 · 现货 ¥158'), post('../posts/overseas-phone.html', '海外手机号五档排行'), post('../posts/giffgaff-guide.html', 'Giffgaff 保姆级教程')] },
      { title: '国行手机配一个写卡器', how: 'iPhone 用户闭眼入 XeSIM X2 Pro（我的主力，码 JUST10 九折）；预算有限选 BeeSIM 蓝牙卡（券后 ¥109）。',
        res: [post('../posts/esim-writer-guide.html', '写卡器五款实测横评'), gear('https://xesim.cc/?DIST=T0VCGw%3D%3D', 'XeSIM X2 Pro · 9 折', 'JUST10'), gear('https://s.tb.cn/c.0xH4jJ', 'BeeSIM · 券后 ¥109', '53642600', '淘宝口令')] },
      { title: '（进阶）低成本美国号 Saily', opt: true, how: '首月 $0.98、月租 $0.99 的美国真实蜂窝号。照我的长文一步步来——操作顺序错了拿不到最低价。',
        res: [post('https://x.com/AI_Jasonyu/status/2080877134319624492', 'Saily 全流程教程（X 长文）'), gear('https://saily.com', 'Saily · 结账立减 $5', 'ZHIKUI8049')] }
    ]},
    3: { ico: '🏦', name: '开户', k: 'STATION 03 · 金库岛', tasks: [
      { title: '办一张 U 卡应急', how: '注册 StarryBlue，推荐码 MHQK01I，充 U 即可开卡消费——订阅 AI 工具、付海外账单立刻能用。先小额试。',
        res: [post('https://x.com/AI_Jasonyu/status/2087182339080172010', 'StarryBlue 实测教程（X 长文）'), gear('https://x.com/AI_Jasonyu/status/2087182339080172010', 'StarryBlue · 注册推荐码', 'MHQK01I')] },
      { title: '拿下港卡户口', how: '它是券商入金、大额资金的地基。备好港澳通行证 + 三个月住址证明，众安 / 汇丰选一家先开。',
        res: [wip('港卡开户攻略 · 编写中')] }
    ]},
    4: { ico: '💱', name: '通汇', k: 'STATION 04 · 汇流峡', tasks: [
      { title: '算清你的收款路线', how: '打开工具选「我要收款」，勾上你有的账户、选对方从哪付款——排第一的就是你该走的路线。',
        res: [tool('../tools/transfer.html', '汇款手续费对比工具（实时汇率）')] },
      { title: '避开隐藏费用的坑', how: '手续费是小头，汇率加点才是大头。花 10 分钟读完这两篇，一年能省出一部手机。',
        res: [post('../posts/hidden-fees.html', '隐藏费用：汇率加价才是大头'), post('../posts/wise-vs-paypal.html', 'Wise vs PayPal 收款对比')] }
    ]},
    5: { ico: '📈', name: '生财', k: 'STATION 05 · 投资海', tasks: [
      { title: '开一个港美股券商账户', how: '有了港卡入金就顺了。我在用的券商、开户和入金细节正在整理，写好这一站自动点亮。',
        res: [wip('券商开户与入金攻略 · 整理中')] },
      { title: '建立定投纪律', how: '只投闲钱。固定日期、固定金额定投宽基指数，不择时不梭哈——纪律比聪明重要。',
        res: [] }
    ]},
    6: { ico: '🪙', name: '上链', k: 'STATION 06 · 币潮礁', tasks: [
      { title: '注册主流交易所', how: '币安 / OKX 选一家主用，完成 KYC，立刻开启二次验证（2FA）。',
        res: [wip('交易所注册通道 · 整理中')] },
      { title: '学会 U 的安全进出', how: '先小额试转一笔；开地址白名单；每次转账前核对链和地址前后四位——链上没有撤销键。',
        res: [wip('U 的进出安全指南 · 整理中')] },
      { title: '大额资产进冷钱包', how: '助记词手抄两份、异地存放，永远不拍照、不上云、不告诉任何人。',
        res: [wip('冷钱包选购与使用 · 整理中')] }
    ]},
    7: { ico: '⚒️', name: '造船', k: 'STATION 07 · 造船坞', tasks: [
      { title: '一周内上线你的第一个小产品', how: '解决你自己的一个痛点就够。用 AI 写代码，丑没关系——能用就发布，先下水再改装。',
        res: [post('https://x.com/AI_Jasonyu', '我的出海实战合集（X 主页）')] },
      { title: '搭一套 AI 干活的工作流', how: '把 AI 当员工：写代码、做图、写文案都交给它，你只做两件事——选方向、做决策。',
        res: [] },
      { title: '想清楚你的选品逻辑', how: '小市场、真需求、能收钱，三个都满足再动手。别做大而全，我的 20 个 App 全是小而美。',
        res: [wip('万字选品指南 · 站内版整理中')] }
    ]},
    8: { ico: '⛵', name: '扬帆', k: 'STATION 08 · 信风带', tasks: [
      { title: '开一个海外内容阵地', how: 'X 首选：选一个垂直领域每天一条，坚持 90 天。我 9 个月 5 万粉，路径完全可复制。',
        res: [post('https://x.com/AI_Jasonyu', '我的 X 起号实录')] },
      { title: '练好 ASO / SEO 基本功', how: '标题关键词大于一切。产品上线前先做关键词调研，让用户搜得到你，比投广告便宜一百倍。',
        res: [wip('自然流量方法论 · 整理中')] }
    ]}
  };

  /* ── 状态 ── */
  var doneTasks = {};
  try {
    var saved = JSON.parse(localStorage.getItem(TASK_KEY));
    if (saved && typeof saved === 'object') { doneTasks = saved; }
  } catch (e) { /* 隐私模式忽略 */ }

  function saveTasks() {
    try { localStorage.setItem(TASK_KEY, JSON.stringify(doneTasks)); } catch (e) { /* 忽略 */ }
  }

  function taskId(no, i) { return no + '-' + i; }
  function requiredTasks(no) { return STATIONS[no].tasks.filter(function (t) { return !t.opt; }); }
  function stationDoneCount(no) {
    return STATIONS[no].tasks.filter(function (t, i) { return doneTasks[taskId(no, i)]; }).length;
  }
  function stationComplete(no) {
    return STATIONS[no].tasks.every(function (t, i) { return t.opt || doneTasks[taskId(no, i)]; });
  }
  function completeCount() {
    var n = 0;
    for (var i = 1; i <= TOTAL; i++) { if (stationComplete(i)) { n++; } }
    return n;
  }

  /* ── DOM ── */
  var stations = [...document.querySelectorAll('[data-station]')];
  var openNo = null;
  var panel = null;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* ── 资源渲染 ── */
  var KIND_ICON = { post: '📖', tool: '🛠', shop: '🛒', gear: '⚙' };
  function renderRes(r) {
    if (r.kind === 'wip') {
      return '<span class="vt-res wip">🚧 ' + esc(r.label) + '</span>';
    }
    var chip = r.code
      ? '<i class="vt-code" data-copy="' + esc(r.code) + '">' + esc(r.codeLabel || r.code) + ' 复制</i>'
      : '';
    return '<a class="vt-res ' + r.kind + '" href="' + esc(r.href) + '" target="_blank" rel="noopener">' +
      KIND_ICON[r.kind] + ' ' + esc(r.label) + chip + '</a>';
  }

  /* ── 任务面板（原地展开）── */
  function renderPanel(no) {
    var st = STATIONS[no];
    var doneCnt = stationDoneCount(no);
    var complete = stationComplete(no);

    var tasksHtml = st.tasks.map(function (t, i) {
      var id = taskId(no, i);
      var checked = !!doneTasks[id];
      return '<div class="vt-task' + (checked ? ' done' : '') + '" data-task-id="' + id + '">' +
        '<button class="vt-check" data-check aria-label="完成任务">' + (checked ? '✓' : '') + '</button>' +
        '<div class="vt-main">' +
          '<p class="vt-title">' + esc(t.title) + (t.opt ? '<i class="vt-opt">选做</i>' : '') + '</p>' +
          '<p class="vt-how">' + esc(t.how) + '</p>' +
          (t.res.length ? '<div class="vt-resrow">' + t.res.map(renderRes).join('') + '</div>' : '') +
        '</div>' +
      '</div>';
    }).join('');

    var footHtml = complete
      ? '<div class="vt-done-banner">⛵ 本站通关！' + (no < TOTAL ? '<button class="vt-next" data-goto-next>前往下一站 →</button>' : '航线全通，勋章已入账 🏅') + '</div>'
      : '<p class="vt-progress mono">本站进度 ' + doneCnt + ' / ' + st.tasks.length + ' · 勾完必做任务自动通关</p>';

    return '<div class="v-panel" data-panel>' +
      '<div class="vp-head">' +
        '<span class="ico">' + st.ico + '</span>' +
        '<div class="t"><p class="k mono">' + esc(st.k) + '</p><h3>' + esc(st.name) + ' · 任务清单</h3></div>' +
        '<button class="vp-close" data-panel-close aria-label="收起">✕</button>' +
      '</div>' + tasksHtml + footHtml + '</div>';
  }

  function closePanel() {
    if (panel) { panel.remove(); panel = null; openNo = null; }
  }

  function openPanel(no, scroll) {
    closePanel();
    openNo = no;
    var stationEl = stations[no - 1];
    stationEl.insertAdjacentHTML('afterend', renderPanel(no));
    panel = document.querySelector('[data-panel]');
    if (scroll !== false) {
      // 面板在站点下方展开，可能落在视口外——把站点滚到视口上部
      requestAnimationFrame(function () {
        var rect = panel.getBoundingClientRect();
        var vh = window.innerHeight;
        if (rect.top < 0 || rect.bottom > vh * 0.92) {
          stationEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    }
  }

  function refreshPanel() {
    if (!panel || openNo === null) { return; }
    var scroll = window.scrollY;
    var no = openNo;
    closePanel();
    openPanel(no, false);
    window.scrollTo(0, scroll);
  }

  /* ── 地图状态 ── */
  function refreshMap() {
    var next = null;
    stations.forEach(function (el) {
      var no = parseInt(el.dataset.station, 10);
      var complete = stationComplete(no);
      el.classList.toggle('done', complete);
      el.classList.remove('cur');
      if (next === null && !complete) { next = no; }

      var hint = el.querySelector('[data-task-hint]');
      var total = STATIONS[no].tasks.length;
      var cnt = stationDoneCount(no);
      hint.textContent = complete ? '✓ 已通关 · 回顾任务' :
        (cnt > 0 ? cnt + ' / ' + total + ' 任务 · 继续 →' : total + ' 个任务 · 点击展开 →');
    });
    if (next !== null) { stations[next - 1].classList.add('cur'); }

    var n = completeCount();
    document.querySelector('[data-progress-count]').textContent = n + ' / ' + TOTAL;
    document.querySelector('[data-progress-bar]').style.width = (n / TOTAL * 100) + '%';
    document.querySelector('[data-progress-next]').textContent =
      n >= TOTAL ? '🏅 新大陆开拓者' : '下一站 · ' + STATIONS[next].name;

    try { localStorage.setItem('yz-voyage-summary', n + '/' + TOTAL); } catch (e) { /* 忽略 */ }
  }

  /* ── 勋章 ── */
  var badgeMask = document.querySelector('[data-badge-mask]');

  function showBadge(dateStr) {
    document.querySelector('[data-badge-date]').textContent = 'FINISHED · ' + dateStr;
    var text = '我在鱼总的「688 航线」完成了全部八站：通网 · 立号 · 开户 · 通汇 · 生财 · 上链 · 造船 · 扬帆 ⚓ 从 688 元到全球一人公司，这条航线值得每个出海人走一遍 → https://yuzong.ai/voyage/ @AI_Jasonyu';
    document.querySelector('[data-badge-share]').href =
      'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text);
    badgeMask.classList.add('show');
  }

  function maybeAwardBadge() {
    if (completeCount() < TOTAL) { return; }
    var earned = null;
    try { earned = localStorage.getItem(BADGE_KEY); } catch (e) { /* 忽略 */ }
    if (earned) { return; }
    var d = new Date();
    var dateStr = d.getFullYear() + '.' + (d.getMonth() + 1) + '.' + d.getDate();
    try { localStorage.setItem(BADGE_KEY, dateStr); } catch (e) { /* 忽略 */ }
    setTimeout(function () { showBadge(dateStr); }, 500);
  }

  document.querySelector('[data-badge-close]').addEventListener('click', function () {
    badgeMask.classList.remove('show');
  });
  badgeMask.addEventListener('click', function (e) {
    if (e.target === badgeMask) { badgeMask.classList.remove('show'); }
  });

  /* ── 事件 ── */
  stations.forEach(function (el) {
    el.addEventListener('click', function (e) {
      if (e.target.closest('a')) { return; }
      var no = parseInt(el.dataset.station, 10);
      if (openNo === no) { closePanel(); } else { openPanel(no); }
    });
  });

  document.addEventListener('click', function (e) {
    // 收起面板
    if (e.target.closest('[data-panel-close]')) { closePanel(); return; }

    // 前往下一站
    if (e.target.closest('[data-goto-next]')) {
      var nextNo = openNo < TOTAL ? openNo + 1 : null;
      if (nextNo) { openPanel(nextNo); }
      return;
    }

    // 勾任务
    var check = e.target.closest('[data-check]');
    if (check) {
      var id = check.closest('[data-task-id]').dataset.taskId;
      if (doneTasks[id]) { delete doneTasks[id]; } else { doneTasks[id] = true; }
      saveTasks();
      refreshPanel();
      refreshMap();
      maybeAwardBadge();
      return;
    }

    // 复制优惠码
    var chip = e.target.closest('[data-copy]');
    if (chip) {
      e.preventDefault();
      e.stopPropagation();
      var code = chip.dataset.copy;
      var ok = function () { chip.textContent = '✓ 已复制 ' + code; };
      if (navigator.clipboard) { navigator.clipboard.writeText(code).then(ok).catch(ok); } else { ok(); }
    }
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closePanel(); badgeMask.classList.remove('show'); }
  });

  refreshMap();
})();
