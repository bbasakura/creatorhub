'use strict';

/**
 * 汇款手续费对比 · 静态版
 * 计算逻辑从主项目 app/utils/fee-math.ts 原样移植（纯函数），
 * 数据文件从 app/data/ 拷贝，季度更新时同步替换 tools/data/*.json 即可。
 */

/*═══════════ 费用计算（fee-math.ts 移植）═══════════*/

function getExchangeRate(from, to, rates) {
  if (from === to) { return 1; }
  const fromRate = rates.rates[from];
  const toRate = rates.rates[to];
  if (fromRate === undefined || toRate === undefined) {
    throw new Error('Exchange rate not found for ' + from + ' or ' + to);
  }
  return toRate / fromRate;
}

function convertCurrency(amount, from, to, rates) {
  return amount * getExchangeRate(from, to, rates);
}

function applyFeeBounds(calculatedFee, minimumFee, maximumFee, sourceCurrency, rates) {
  let fee = calculatedFee;
  if (minimumFee !== null) {
    fee = Math.max(fee, convertCurrency(minimumFee.amount, minimumFee.currency, sourceCurrency, rates));
  }
  if (maximumFee !== null) {
    fee = Math.min(fee, convertCurrency(maximumFee.amount, maximumFee.currency, sourceCurrency, rates));
  }
  return fee;
}

function sumFeesInCurrency(fees, targetCurrency, rates) {
  return fees.reduce(function (sum, fee) {
    if (fee.amount === 0) { return sum; }
    return sum + convertCurrency(fee.amount, fee.currency, targetCurrency, rates);
  }, 0);
}

function buildSendFeeComponents(route, amount, boundedPercentFee, rates) {
  const components = [];

  if (route.fees.fixedFee.amount > 0) {
    components.push({
      label: '转账手续费',
      amount: convertCurrency(route.fees.fixedFee.amount, route.fees.fixedFee.currency, route.sourceCurrency, rates),
      currency: route.sourceCurrency
    });
  }
  if (boundedPercentFee > 0) {
    components.push({ label: '比例费用', amount: boundedPercentFee, currency: route.sourceCurrency });
  }
  if (route.fees.swiftFee.amount > 0) {
    components.push({
      label: 'SWIFT电报费',
      amount: convertCurrency(route.fees.swiftFee.amount, route.fees.swiftFee.currency, route.sourceCurrency, rates),
      currency: route.sourceCurrency
    });
  }
  if (route.fees.intermediaryFee.amount > 0) {
    components.push({
      label: '中间行费用',
      amount: convertCurrency(route.fees.intermediaryFee.amount, route.fees.intermediaryFee.currency, route.sourceCurrency, rates),
      currency: route.sourceCurrency
    });
  }
  if (route.fees.fxMarkup > 0) {
    const midRate = getExchangeRate(route.sourceCurrency, route.destinationCurrency, rates);
    components.push({
      label: '汇率加价',
      amount: amount * route.fees.fxMarkup * midRate,
      currency: route.destinationCurrency
    });
  }
  if (route.fees.receivingFee.amount > 0) {
    components.push({
      label: '收款方入账费',
      amount: route.fees.receivingFee.amount,
      currency: route.fees.receivingFee.currency
    });
  }
  return components;
}

function calculateSendFees(route, amount, rates) {
  const rawPercentFee = amount * route.fees.percentageFee;
  const boundedPercentFee = applyFeeBounds(
    rawPercentFee, route.fees.minimumFee, route.fees.maximumFee, route.sourceCurrency, rates
  );
  const fixedFeeTotal = sumFeesInCurrency(
    [route.fees.fixedFee, route.fees.swiftFee, route.fees.intermediaryFee],
    route.sourceCurrency, rates
  );
  const totalFeeSource = boundedPercentFee + fixedFeeTotal;

  const midMarketRate = getExchangeRate(route.sourceCurrency, route.destinationCurrency, rates);
  const effectiveRate = midMarketRate * (1 - route.fees.fxMarkup);

  const receivingFeeInDest = route.fees.receivingFee.amount === 0
    ? 0
    : convertCurrency(route.fees.receivingFee.amount, route.fees.receivingFee.currency, route.destinationCurrency, rates);
  const amountReceived = (amount - totalFeeSource) * effectiveRate - receivingFeeInDest;

  return {
    totalFeeSourceCurrency: totalFeeSource,
    totalFeePercent: amount > 0 ? totalFeeSource / amount : 0,
    effectiveExchangeRate: effectiveRate,
    amountReceived: amountReceived,
    feeComponents: buildSendFeeComponents(route, amount, boundedPercentFee, rates)
  };
}

function calculateReceiveFees(route, amount, rates) {
  const incomingFeeInPayerCurrency = route.fees.incomingFee.amount === 0
    ? 0
    : convertCurrency(route.fees.incomingFee.amount, route.fees.incomingFee.currency, route.payerCurrency, rates);

  const afterIncoming = amount - incomingFeeInPayerCurrency;
  const conversionFee = afterIncoming * route.fees.conversionFee;
  const afterConversion = afterIncoming - conversionFee;

  const midMarketRate = getExchangeRate(route.payerCurrency, route.receiveCurrency, rates);
  const effectiveRate = midMarketRate * (1 - route.fees.fxMarkup);
  const inReceiveCurrency = afterConversion * effectiveRate;

  const withdrawalFeeInReceive = route.fees.withdrawalFee.amount === 0
    ? 0
    : convertCurrency(route.fees.withdrawalFee.amount, route.fees.withdrawalFee.currency, route.receiveCurrency, rates);
  const amountReceived = inReceiveCurrency - withdrawalFeeInReceive;

  const fxLossInPayer = route.fees.fxMarkup > 0 && midMarketRate > 0
    ? (afterConversion * midMarketRate * route.fees.fxMarkup) / midMarketRate
    : 0;
  const withdrawalInPayer = withdrawalFeeInReceive > 0 && midMarketRate > 0
    ? withdrawalFeeInReceive / midMarketRate
    : 0;
  const totalFeeSource = incomingFeeInPayerCurrency + conversionFee + fxLossInPayer + withdrawalInPayer;

  const feeComponents = [];
  if (incomingFeeInPayerCurrency > 0) {
    feeComponents.push({ label: '入账手续费', amount: incomingFeeInPayerCurrency, currency: route.payerCurrency });
  }
  if (conversionFee > 0) {
    feeComponents.push({ label: '换汇费用', amount: conversionFee, currency: route.payerCurrency });
  }
  if (route.fees.fxMarkup > 0) {
    feeComponents.push({
      label: '汇率加价',
      amount: afterConversion * midMarketRate * route.fees.fxMarkup,
      currency: route.receiveCurrency
    });
  }
  if (withdrawalFeeInReceive > 0) {
    feeComponents.push({ label: '提现费用', amount: withdrawalFeeInReceive, currency: route.receiveCurrency });
  }

  return {
    totalFeeSourceCurrency: totalFeeSource,
    totalFeePercent: amount > 0 ? totalFeeSource / amount : 0,
    effectiveExchangeRate: effectiveRate,
    amountReceived: amountReceived,
    feeComponents: feeComponents
  };
}

/*═══════════ UI ═══════════*/

const CURRENCY_NAMES = {
  USD: '美元 USD', CNY: '人民币 CNY', HKD: '港币 HKD', GBP: '英镑 GBP',
  EUR: '欧元 EUR', SGD: '新币 SGD', AUD: '澳元 AUD', CAD: '加元 CAD', JPY: '日元 JPY'
};

const TAG_NAMES = {
  'recommended': '推荐', 'low-fee': '低费用', 'fast': '快速',
  'business': '企业向', 'cheapest': '最便宜', 'china-hk': '中港',
  'ecommerce': '电商', 'expensive': '费用高', 'free': '免费',
  'free-send': '发送免费', 'freelancer': '自由职业', 'full-amount': '全额到账',
  'instant': '即时', 'kol': 'KOL', 'no-fee': '零费用', 'slow': '较慢',
  'traditional': '传统电汇', 'usd-only': '仅美元', 'wide-coverage': '覆盖广',
  'wise-rate': 'Wise 汇率'
};

const els = {
  tabs: [...document.querySelectorAll('[data-mode]')],
  form: document.querySelector('[data-calc]'),
  from: document.querySelector('[data-from]'),
  to: document.querySelector('[data-to]'),
  amount: document.querySelector('[data-amount]'),
  labelFrom: document.querySelector('[data-label-from]'),
  labelTo: document.querySelector('[data-label-to]'),
  labelAmount: document.querySelector('[data-label-amount]'),
  results: document.querySelector('[data-results]'),
  version: document.querySelector('[data-data-version]'),
  ratesNote: document.querySelector('[data-rates-note]'),
  maChips: document.querySelector('[data-ma-chips]'),
  payerFilter: document.querySelector('[data-payer-filter]'),
  payerChips: document.querySelector('[data-payer-chips]'),
  pfToggle: document.querySelector('[data-pf-toggle]'),
  pfBody: document.querySelector('[data-pf-body]'),
  pfText: document.querySelector('[data-pf-text]'),
  pfArrow: document.querySelector('[data-pf-arrow]')
};

/*═══════════ 我的账户（本地保存，影响排序分组）═══════════*/

const ACCOUNTS_KEY = 'yz-my-accounts';
const ACCOUNT_LABELS = {
  wise: 'Wise', airwallex: '空中云汇', paypal: 'PayPal', mercury: 'Mercury（美国）',
  hsbc_hk: '汇丰香港', bochk: '中银香港', za_bank: '众安银行', airstar: '天星银行',
  worldfirst: '万里汇', cn_bank: '大陆银行卡'
};

let myAccounts = new Set();
try {
  const saved = JSON.parse(localStorage.getItem(ACCOUNTS_KEY));
  if (Array.isArray(saved)) { myAccounts = new Set(saved); }
} catch (e) { /* 隐私模式等场景忽略 */ }

function saveAccounts() {
  try { localStorage.setItem(ACCOUNTS_KEY, JSON.stringify([...myAccounts])); } catch (e) { /* 忽略 */ }
}

function renderAccountChips() {
  if (!els.maChips || !DB) { return; }
  els.maChips.innerHTML = DB.platforms.map(function (p) {
    const label = ACCOUNT_LABELS[p.id] || p.nameZh || p.name;
    const on = myAccounts.has(p.id);
    return '<button type="button" class="ma-chip' + (on ? ' active' : '') + '" data-acct="' + esc(p.id) + '">' +
      (on ? '✓ ' : '') + esc(label) + '</button>';
  }).join('');
}

function routeKeyPlatform(route) {
  return mode === 'send' ? route.sourcePlatformId : route.receivePlatformId;
}

/*═══════════ 对方从哪付款（收款模式筛选）═══════════*/

const PAYER_KEY = 'yz-payer-region';
const PAYER_OPTIONS = [
  ['', '不限'], ['US', '美国'], ['HK', '香港'], ['SG', '新加坡'],
  ['CN', '中国大陆'], ['GB', '英国'], ['EU', '欧盟']
];

let payerRegion = '';
try { payerRegion = localStorage.getItem(PAYER_KEY) || ''; } catch (e) { /* 忽略 */ }

function renderPayerChips() {
  if (!els.payerChips) { return; }
  els.payerChips.innerHTML = PAYER_OPTIONS.map(function (opt) {
    const on = payerRegion === opt[0];
    return '<button type="button" class="ma-chip' + (on ? ' active' : '') + '" data-payer="' + opt[0] + '">' +
      (on ? '✓ ' : '') + opt[1] + '</button>';
  }).join('');
}

function payerMatches(route) {
  if (mode !== 'receive' || !payerRegion) { return true; }
  return route.payerRegion === payerRegion || route.payerRegion === 'GLOBAL';
}

/** 折叠摘要：把当前筛选状态浓缩成一行 */
function updatePfSummary() {
  if (!els.pfText) { return; }
  const parts = [];
  if (myAccounts.size > 0) { parts.push('我的账户 ' + myAccounts.size + ' 个'); }
  if (mode === 'receive' && payerRegion) {
    const label = (PAYER_OPTIONS.filter(function (o) { return o[0] === payerRegion; })[0] || [])[1];
    if (label) { parts.push('对方：' + label); }
  }
  els.pfText.textContent = parts.length
    ? '个性化 · ' + parts.join(' · ')
    : '个性化（选填）：告诉我你有哪些账户' + (mode === 'receive' ? '、对方从哪付款' : '');
  els.pfToggle.classList.toggle('has-filters', parts.length > 0);
}

let DB = null;   // { rates, send, receive, platforms }
let mode = new URLSearchParams(location.search).get('mode') === 'receive' ? 'receive' : 'send';

function esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}

function fmtMoney(amount, currency) {
  try {
    return new Intl.NumberFormat('zh-CN', {
      style: 'currency', currency: currency, maximumFractionDigits: 2
    }).format(amount);
  } catch (e) {
    return amount.toFixed(2) + ' ' + currency;
  }
}

function currencyLabel(code) { return CURRENCY_NAMES[code] || code; }

function routesForMode() {
  return mode === 'send' ? DB.send.routes : DB.receive.routes;
}

function pairOf(route) {
  return mode === 'send'
    ? [route.sourceCurrency, route.destinationCurrency]
    : [route.payerCurrency, route.receiveCurrency];
}

/* 表单选项：来源币种 → 可用目标币种 */
function populateSelects(keepFrom, keepTo) {
  const routes = routesForMode();
  const froms = [...new Set(routes.map(function (r) { return pairOf(r)[0]; }))];

  els.from.innerHTML = froms.map(function (c) {
    return '<option value="' + c + '">' + esc(currencyLabel(c)) + '</option>';
  }).join('');
  if (keepFrom && froms.includes(keepFrom)) { els.from.value = keepFrom; }

  const from = els.from.value;
  const tos = [...new Set(routes.filter(function (r) { return pairOf(r)[0] === from; })
    .map(function (r) { return pairOf(r)[1]; }))];

  els.to.innerHTML = tos.map(function (c) {
    return '<option value="' + c + '">' + esc(currencyLabel(c)) + '</option>';
  }).join('');
  if (keepTo && tos.includes(keepTo)) { els.to.value = keepTo; }
}

function applyModeLabels() {
  if (mode === 'send') {
    els.labelFrom.textContent = 'FROM · 汇出币种';
    els.labelTo.textContent = 'TO · 收款币种';
    els.labelAmount.textContent = 'AMOUNT · 汇出金额';
  } else {
    els.labelFrom.textContent = 'PAYER · 对方支付币种';
    els.labelTo.textContent = 'KEEP · 我要收成';
    els.labelAmount.textContent = 'AMOUNT · 对方支付金额';
  }
}

function platformName(id) {
  if (!id) { return ''; }
  const p = DB.platforms.find(function (x) { return x.id === id; });
  return p ? p.name : id;
}

function checkLimit(route, amount) {
  if (!route.limits) { return null; }
  const cur = mode === 'send' ? route.sourceCurrency : route.payerCurrency;
  const inLimitCur = convertCurrency(amount, cur, route.limits.currency, DB.rates);
  if (inLimitCur < route.limits.minAmount) {
    return '低于最低限额 ' + fmtMoney(route.limits.minAmount, route.limits.currency);
  }
  if (inLimitCur > route.limits.maxAmount) {
    return '超出单笔限额 ' + fmtMoney(route.limits.maxAmount, route.limits.currency);
  }
  return null;
}

function renderSteps(route) {
  if (!route.steps || !route.steps.length) { return ''; }
  const steps = route.steps.map(function (s) {
    const link = s.affiliateUrl
      ? ' <a href="' + esc(s.affiliateUrl) + '" target="_blank" rel="noopener">前往 ↗</a>'
      : '';
    const tips = (s.tips || []).map(function (t) {
      return '<p class="tip">' + esc(t) + '</p>';
    }).join('');
    return '<div class="step"><span class="step-no">' + s.order + '</span><div>' +
           '<h5>' + esc(s.action) + link + '</h5>' +
           '<p>' + esc(s.detail || '') + '</p>' + tips + '</div></div>';
  }).join('');
  return '<details><summary>操作步骤（' + route.steps.length + ' 步）</summary><div class="steps">' + steps + '</div></details>';
}

function renderCard(route, breakdown, index, limitWarn) {
  const destCurrency = mode === 'send' ? route.destinationCurrency : route.receiveCurrency;
  const srcCurrency = mode === 'send' ? route.sourceCurrency : route.payerCurrency;
  const best = index === 0 && !limitWarn;

  const tags = (route.tags || []).map(function (t) {
    return '<span class="r-tag">' + esc(TAG_NAMES[t] || t) + '</span>';
  }).join('');

  const fees = breakdown.feeComponents.length
    ? '<details open><summary>费用构成（' + breakdown.feeComponents.length + ' 项）</summary><div class="fee-list">' +
      breakdown.feeComponents.map(function (f) {
        return '<div class="fee-row"><span>' + esc(f.label) + '</span><b>' + fmtMoney(f.amount, f.currency) + '</b></div>';
      }).join('') + '</div></details>'
    : '<details><summary>费用构成</summary><div class="fee-list"><div class="fee-row"><span>零费用路线</span><b>' + fmtMoney(0, srcCurrency) + '</b></div></div></details>';

  const caveats = (route.caveats || []).length
    ? '<p class="caveats">' + route.caveats.map(function (c) { return '<span>' + esc(c) + '</span>'; }).join('') + '</p>'
    : '';

  const platform = mode === 'receive' ? platformName(route.receivePlatformId) : '';

  return '<article class="r-card' + (best ? ' best' : '') + '">' +
    (best ? '<span class="best-ribbon">最划算 · BEST</span>' : '') +
    '<div class="r-top">' +
      '<span class="r-rank mono">' + String(index + 1).padStart(2, '0') + '</span>' +
      '<h3 class="r-name">' + esc(route.name) + '</h3>' +
      (platform ? '<span class="r-tag">' + esc(platform) + '</span>' : '') +
      '<div class="r-tags">' + tags + '</div>' +
    '</div>' +
    '<div class="r-main">' +
      '<p class="r-received"><b>' + fmtMoney(breakdown.amountReceived, destCurrency) + '</b><span> 到手</span></p>' +
      '<div class="r-meta">' +
        '<span>总费用 <b>' + fmtMoney(breakdown.totalFeeSourceCurrency, srcCurrency) + '</b> <b class="fee-pct">(' + (breakdown.totalFeePercent * 100).toFixed(2) + '%)</b></span>' +
        '<span>汇率 <b>' + breakdown.effectiveExchangeRate.toFixed(4) + '</b></span>' +
        '<span>到账 <b>' + esc(route.speed || '—') + '</b></span>' +
        (limitWarn ? '<span class="limit-warn">' + esc(limitWarn) + '</span>' : '') +
      '</div>' +
    '</div>' +
    fees + renderSteps(route) + caveats +
  '</article>';
}

function calculate() {
  const from = els.from.value;
  const to = els.to.value;
  const amount = parseFloat(els.amount.value);

  if (!(amount > 0)) {
    els.results.innerHTML = '<div class="empty-state">请输入大于 0 的金额（支持小数）</div>';
    return;
  }
  if (!from || !to) { return; }

  const pairMatched = routesForMode().filter(function (r) {
    const p = pairOf(r);
    return p[0] === from && p[1] === to;
  });
  const matched = pairMatched.filter(payerMatches);

  if (!matched.length) {
    if (pairMatched.length && payerRegion) {
      const label = (PAYER_OPTIONS.filter(function (o) { return o[0] === payerRegion; })[0] || [])[1] || payerRegion;
      els.results.innerHTML = '<div class="empty-state">「对方从' + label + '付款」的筛选下，这条路线没有匹配方案——试试把付款方切回「不限」。</div>';
    } else {
      els.results.innerHTML = '<div class="empty-state">这条路线还没有收录数据——告诉我你的场景，我来补。</div>';
    }
    return;
  }

  const calc = mode === 'send' ? calculateSendFees : calculateReceiveFees;

  const scored = matched.map(function (route) {
    return { route: route, breakdown: calc(route, amount, DB.rates), limitWarn: checkLimit(route, amount) };
  }).sort(function (a, b) {
    // 超限路线沉底，其余按到手金额降序
    if (!!a.limitWarn !== !!b.limitWarn) { return a.limitWarn ? 1 : -1; }
    return b.breakdown.amountReceived - a.breakdown.amountReceived;
  });

  // 勾选了「我的账户」→ 现有账户可用的方案排前，其余折叠
  if (myAccounts.size > 0) {
    const owned = scored.filter(function (s) { return myAccounts.has(routeKeyPlatform(s.route)); });
    const others = scored.filter(function (s) { return !myAccounts.has(routeKeyPlatform(s.route)); });

    let html = '';
    if (owned.length) {
      html += '<p class="group-head mono">✓ 用你现有的账户就能走（' + owned.length + ' 条）</p>';
      html += owned.map(function (s, i) { return renderCard(s.route, s.breakdown, i, s.limitWarn); }).join('');
    } else {
      html += '<div class="empty-state">你勾选的账户走不通这条路线——看看下面需要新开的方案，或换条路线。</div>';
    }
    if (others.length) {
      html += '<button type="button" class="group-toggle" data-toggle-others>需要新开账户的方案（' + others.length + ' 条）▾</button>';
      html += '<div class="group-others" hidden>' +
        others.map(function (s, i) { return renderCard(s.route, s.breakdown, owned.length + i, s.limitWarn); }).join('') +
        '</div>';
    }
    els.results.innerHTML = html;
    return;
  }

  els.results.innerHTML = scored.map(function (s, i) {
    return renderCard(s.route, s.breakdown, i, s.limitWarn);
  }).join('');
}

function switchMode(next) {
  mode = next;
  els.tabs.forEach(function (t) { t.classList.toggle('active', t.dataset.mode === next); });
  if (els.payerFilter) { els.payerFilter.hidden = next !== 'receive'; }
  applyModeLabels();
  populateSelects();
  updatePfSummary();
  els.results.innerHTML = '';
  history.replaceState(null, '', '?mode=' + next);
  calculate();
}

/*═══════════ 启动 ═══════════*/

/** 实时汇率：/api/rates（边缘缓存 6h），超时 8s，失败自动重试一次，仍失败降级 */
function fetchLiveRatesOnce() {
  return Promise.race([
    fetch('/api/rates').then(function (r) { return r.ok ? r.json() : null; }),
    new Promise(function (resolve) { setTimeout(function () { resolve(null); }, 8000); })
  ]).catch(function () { return null; });
}

function fetchLiveRates() {
  return fetchLiveRatesOnce().then(function (result) {
    if (result) { return result; }
    return new Promise(function (resolve) { setTimeout(resolve, 1000); }).then(fetchLiveRatesOnce);
  });
}

Promise.all([
  fetch('./data/exchange-rates.json').then(function (r) { return r.json(); }),
  fetch('./data/send-routes.json').then(function (r) { return r.json(); }),
  fetch('./data/receive-routes.json').then(function (r) { return r.json(); }),
  fetch('./data/platforms.json').then(function (r) { return r.json(); }),
  fetchLiveRates()
]).then(function (loaded) {
  var live = loaded[4];
  var rates = loaded[0];
  var rateNote;

  function fmtWhen(iso) {
    var d = iso ? new Date(iso) : null;
    return d && !isNaN(d) ? (d.getMonth() + 1) + '月' + d.getDate() + '日' : '今日';
  }

  // 实时失败时，先找上次成功的本地缓存（48 小时内有效），再退到打包快照
  if (!live) {
    try {
      var cached = JSON.parse(localStorage.getItem('yz-live-rates'));
      if (cached && cached.rates && Date.now() - cached.fetchedAt < 48 * 3600e3) {
        live = cached;
        live._fromCache = true;
      }
    } catch (e) { /* 忽略 */ }
  }

  if (live && live.rates) {
    rates = { version: '实时', updatedAt: live.updatedAt, rates: live.rates };
    rateNote = '汇率 ' + fmtWhen(live.updatedAt) + '中间价' + (live._fromCache ? '（本地缓存）' : ' · 每日更新');
    if (!live._fromCache) {
      try {
        localStorage.setItem('yz-live-rates', JSON.stringify({ rates: live.rates, updatedAt: live.updatedAt, fetchedAt: Date.now() }));
      } catch (e) { /* 忽略 */ }
    }
  } else {
    rateNote = '汇率 ' + rates.updatedAt + ' 快照（实时源暂不可用）';
  }

  DB = {
    rates: rates,
    send: loaded[1],
    receive: loaded[2],
    platforms: loaded[3].platforms || loaded[3]
  };

  els.version.textContent = rateNote + ' · 费率数据 ' + loaded[0].version;
  els.ratesNote.textContent = 'RATES · ' + rateNote + '（USD/CNY ' + (DB.rates.rates.CNY ? DB.rates.rates.CNY.toFixed(3) : '—') + '）— 仅供参考，以平台实时报价为准';

  els.tabs.forEach(function (tab) {
    tab.addEventListener('click', function () { switchMode(this.dataset.mode); });
  });

  els.from.addEventListener('change', function () { populateSelects(this.value); calculate(); });

  els.form.addEventListener('submit', function (e) {
    e.preventDefault();
    calculate();
  });

  // 个性化区折叠开关
  if (els.pfToggle) {
    els.pfToggle.addEventListener('click', function () {
      els.pfBody.hidden = !els.pfBody.hidden;
      els.pfArrow.textContent = els.pfBody.hidden ? '▾' : '▴';
    });
  }

  // 即改即算：金额防抖 400ms，币种立即
  let amountTimer = null;
  els.amount.addEventListener('input', function () {
    clearTimeout(amountTimer);
    amountTimer = setTimeout(calculate, 400);
  });
  els.to.addEventListener('change', calculate);

  // 我的账户：勾选切换 → 保存并重新分组
  if (els.maChips) {
    renderAccountChips();
    els.maChips.addEventListener('click', function (e) {
      const chip = e.target.closest('[data-acct]');
      if (!chip) { return; }
      const id = chip.dataset.acct;
      if (myAccounts.has(id)) { myAccounts.delete(id); } else { myAccounts.add(id); }
      saveAccounts();
      renderAccountChips();
      updatePfSummary();
      calculate();
    });
  }

  // 对方付款地：单选切换 → 保存并重算
  if (els.payerChips) {
    renderPayerChips();
    els.payerChips.addEventListener('click', function (e) {
      const chip = e.target.closest('[data-payer]');
      if (!chip) { return; }
      payerRegion = chip.dataset.payer;
      try { localStorage.setItem(PAYER_KEY, payerRegion); } catch (err) { /* 忽略 */ }
      renderPayerChips();
      updatePfSummary();
      calculate();
    });
  }

  // 「需要新开账户」折叠展开
  els.results.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-toggle-others]');
    if (!btn) { return; }
    const box = els.results.querySelector('.group-others');
    if (!box) { return; }
    box.hidden = !box.hidden;
    btn.textContent = btn.textContent.replace(box.hidden ? '▴' : '▾', box.hidden ? '▾' : '▴');
  });

  switchMode(mode);
}).catch(function (err) {
  els.results.innerHTML = '<div class="empty-state">数据加载失败：' + esc(err.message) + '<br>请通过本地服务器访问（而非直接双击打开文件）。</div>';
});
