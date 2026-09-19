'use strict';

/**
 * yuzong.ai · 「出海志」交互层
 * 1. 页签切换（滑动指示线 + hash 路由 + 错落浮现重触发）
 * 2. 罗盘指针跟随鼠标
 * 3. 船长面板底部海浪画布
 * 4. 数据条计数动画
 * 5. 工具卡 3D 倾斜 + 分类筛选
 * 6. 留言表单唤起邮件
 */

const CONTACT_EMAIL = 'hi@yuzong.ai';
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const finePointer = window.matchMedia('(pointer: fine)').matches;


/*── 0. 昼航 / 夜航 ──*/

const THEME_KEY = 'yuzong-theme';

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
}

(function initTheme() {
  let stored = null;
  try { stored = localStorage.getItem(THEME_KEY); } catch (e) { /* 隐私模式下不可用，跟随系统 */ }
  const system = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  applyTheme(stored || system);
})();

const themeToggle = document.querySelector('[data-theme-toggle]');

if (themeToggle) {
  themeToggle.addEventListener('click', function () {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* 忽略写入失败 */ }
  });
}


/*── 1. 页签切换 ──*/

const navLinks = [...document.querySelectorAll('[data-nav]')];
const pages = [...document.querySelectorAll('[data-page]')];
const navInk = document.querySelector('[data-nav-ink]');

function moveInk(link) {
  if (!navInk || !link) { return; }
  navInk.style.width = (link.offsetWidth - 4) + 'px';
  navInk.style.transform = 'translateX(' + link.offsetLeft + 'px)';
}

function restartReveals(page) {
  page.querySelectorAll('.reveal').forEach(function (el) {
    el.style.animation = 'none';
    void el.offsetWidth;           // 强制重排，重触发入场动画
    el.style.animation = '';
  });
}

function showPage(key, updateHash) {
  const target = pages.find(function (p) { return p.dataset.page === key; });
  if (!target) { return; }

  pages.forEach(function (p) { p.classList.toggle('active', p === target); });
  navLinks.forEach(function (l) { l.classList.toggle('active', l.dataset.nav === key); });

  moveInk(navLinks.find(function (l) { return l.dataset.nav === key; }));
  if (!reducedMotion) { restartReveals(target); }
  if (updateHash) { history.replaceState(null, '', '#' + key); }

  window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
  startCounters(target);
}

navLinks.forEach(function (link) {
  link.addEventListener('click', function () { showPage(this.dataset.nav, true); });
});

window.addEventListener('resize', function () {
  moveInk(document.querySelector('.nav-link.active'));
});

// hash 直达（如 yuzong.ai/#tools）
const initial = location.hash.replace('#', '');
showPage(pages.some(function (p) { return p.dataset.page === initial; }) ? initial : 'about', false);


/*── 2. 罗盘指针跟随鼠标 ──*/

const needle = document.querySelector('[data-needle]');
const compass = document.querySelector('.compass');

if (needle && compass && finePointer && !reducedMotion) {
  let raf = null;

  document.addEventListener('mousemove', function (e) {
    if (raf) { return; }
    raf = requestAnimationFrame(function () {
      const box = compass.getBoundingClientRect();
      const cx = box.left + box.width / 2;
      const cy = box.top + box.height / 2;
      const angle = Math.atan2(e.clientX - cx, cy - e.clientY) * 180 / Math.PI;
      needle.style.transform = 'rotate(' + angle.toFixed(1) + 'deg)';
      raf = null;
    });
  });
}

// 罗盘刻度（每 15° 一格）
const ticks = document.querySelector('.c-ticks');
if (ticks) {
  let html = '';
  for (let a = 0; a < 360; a += 15) {
    const rad = a * Math.PI / 180;
    const r1 = 52, r2 = a % 90 === 0 ? 46 : 49;
    html += '<line x1="' + (60 + r1 * Math.sin(rad)).toFixed(1) + '" y1="' + (60 - r1 * Math.cos(rad)).toFixed(1) +
            '" x2="' + (60 + r2 * Math.sin(rad)).toFixed(1) + '" y2="' + (60 - r2 * Math.cos(rad)).toFixed(1) + '"/>';
  }
  ticks.innerHTML = html;
}


/*── 3. 海浪画布 ──*/

const canvas = document.querySelector('[data-waves]');

if (canvas && !reducedMotion) {
  const ctx = canvas.getContext('2d');
  let w = 0, h = 0, t = 0;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.offsetWidth; h = canvas.offsetHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  resize();
  window.addEventListener('resize', resize);

  const LAYERS = [
    { amp: 7, len: 0.016, speed: 0.014, y: 0.45, alpha: 0.30 },
    { amp: 10, len: 0.011, speed: 0.010, y: 0.62, alpha: 0.22 },
    { amp: 14, len: 0.008, speed: 0.007, y: 0.80, alpha: 0.14 }
  ];

  (function draw() {
    ctx.clearRect(0, 0, w, h);
    LAYERS.forEach(function (l, i) {
      ctx.beginPath();
      for (let x = 0; x <= w; x += 3) {
        const y = h * l.y + Math.sin(x * l.len + t * l.speed * 60 + i * 2.1) * l.amp;
        if (x === 0) { ctx.moveTo(x, y); } else { ctx.lineTo(x, y); }
      }
      ctx.strokeStyle = 'rgba(156, 200, 209, ' + l.alpha + ')';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    });
    t += 0.016;
    requestAnimationFrame(draw);
  })();
}


/*── 4. 数据条计数动画 ──*/

function startCounters(scope) {
  scope.querySelectorAll('[data-count]').forEach(function (el) {
    if (el.dataset.done) { return; }
    el.dataset.done = '1';

    const target = parseInt(el.dataset.count, 10);
    const suffix = el.dataset.suffix || '';

    if (reducedMotion) { el.textContent = target + suffix; return; }

    const start = performance.now();
    const dur = 1100;

    (function tick(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased) + suffix;
      if (p < 1) { requestAnimationFrame(tick); }
    })(start);
  });
}


/*── 5. 工具卡：3D 倾斜 + 分类筛选 ──*/

if (finePointer && !reducedMotion) {
  document.querySelectorAll('[data-tilt]').forEach(function (card) {
    card.addEventListener('mousemove', function (e) {
      const r = card.getBoundingClientRect();
      const rx = ((e.clientY - r.top) / r.height - 0.5) * -5;
      const ry = ((e.clientX - r.left) / r.width - 0.5) * 5;
      card.style.transform = 'perspective(700px) rotateX(' + rx.toFixed(2) + 'deg) rotateY(' + ry.toFixed(2) + 'deg) translateY(-4px)';
    });
    card.addEventListener('mouseleave', function () {
      card.style.transform = '';
    });
  });
}

const filterBtns = [...document.querySelectorAll('[data-filter]')];
const toolCards = [...document.querySelectorAll('[data-cat]')];

filterBtns.forEach(function (btn) {
  btn.addEventListener('click', function () {
    filterBtns.forEach(function (b) { b.classList.toggle('active', b === btn); });
    const value = btn.dataset.filter;
    toolCards.forEach(function (card) {
      card.classList.toggle('is-hidden', value !== '全部' && card.dataset.cat !== value);
    });
  });
});


/*── 6. 留言表单 ──*/

const form = document.querySelector('[data-form]');
const sendBtn = document.querySelector('[data-send]');

if (form && sendBtn) {
  form.addEventListener('input', function () {
    if (form.checkValidity()) {
      sendBtn.removeAttribute('disabled');
    } else {
      sendBtn.setAttribute('disabled', '');
    }
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    const data = new FormData(form);
    const name = String(data.get('fullname') || '').trim();
    const replyTo = String(data.get('email') || '').trim();
    const message = String(data.get('message') || '').trim();

    const subject = encodeURIComponent('【yuzong.ai】来自 ' + name + ' 的留言');
    const body = encodeURIComponent(message + '\n\n—\n称呼：' + name + '\n回信邮箱：' + replyTo);

    window.location.href = 'mailto:' + CONTACT_EMAIL + '?subject=' + subject + '&body=' + body;
  });
}


/*── 7. 装备 / 联系 / 打赏：从 links.js 渲染 ──*/

function esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}

function copyChip(code) {
  return '<button class="copy-chip mono" type="button" data-copy="' + esc(code) + '">' +
         '邀请码 <b>' + esc(code) + '</b><span class="copy-hint">复制</span></button>';
}

// 装备网格
(function renderGear() {
  const root = document.querySelector('[data-gear-root]');
  if (!root || !window.YZ_GEAR) { return; }

  root.innerHTML = window.YZ_GEAR.map(function (sec) {
    const items = sec.items.map(function (it) {
      const ready = !!it.url;
      const inner =
        '<p class="gear-tag mono">' + esc(it.tag) + (it.hot ? '<b class="gear-hot">主推</b>' : '') + '</p>' +
        '<h4>' + esc(it.name) + '</h4>' +
        '<p class="gear-desc">' + esc(it.desc) + '</p>' +
        '<div class="gear-foot mono">' +
          ((it.code || it.deal)
            ? '<div class="gear-marks">' +
                (it.code ? copyChip(it.code) : '') +
                (it.deal ? '<b class="gear-deal">' + esc(it.deal) + '</b>' : '') +
              '</div>'
            : '') +
          (ready ? '<span class="go">前往 →</span>' : '<span class="gear-soon">整理中</span>') +
        '</div>';
      return ready
        ? '<a class="gear-item" href="' + esc(it.url) + '"' +
            (it.url.startsWith('http') ? ' target="_blank" rel="noopener"' : '') + '>' + inner + '</a>'
        : '<div class="gear-item is-soon">' + inner + '</div>';
    }).join('');

    return '<h3 class="sec-title"><span class="mono sec-no">' + esc(sec.no) + '</span>' +
           esc(sec.section) + '</h3><div class="gear-grid">' + items + '</div>';
  }).join('');
})();

// 联系卡片
(function renderContact() {
  const root = document.querySelector('[data-contact-grid]');
  if (!root || !window.YZ_CONTACT) { return; }

  const C = window.YZ_CONTACT;
  const g = C.group || {};
  const cards = [
    { k: 'X / TWITTER', v: C.x, note: '日常更新 · 私信最快' },
    { k: '公众号', v: C.wechat, note: '长文首发 · 鱼总聊AI' },
    // 韭菜群：特殊高亮卡，点击打开 X 介绍文章；入群 = 加微信
    { k: '🌱 ' + (g.name || '韭菜群') + (g.price ? ' · ' + g.price : ''), hot: true,
      v: { handle: g.wechat ? '微信 ' + g.wechat + '（备注：' + (g.wechatNote || '进群') + '）' : '', url: g.url || '' },
      note: g.note || '同频小圈子' },
    { k: 'TELEGRAM', v: C.telegram, note: '一对一咨询' },
    { k: 'MAIL', v: C.mail, note: '最稳的通道 · 48h 内回' },
    { k: 'GITHUB', v: C.github, note: '开源与工具' }
  ];

  root.innerHTML = cards.map(function (c) {
    const has = !!(c.v && (c.v.url || c.v.handle));
    const handle = c.v && c.v.handle ? c.v.handle : (c.hot ? '开垦中 · 即将开放' : '整理中');
    const cls = 'contact-card' + (c.hot ? ' hot' : '') + (has ? '' : ' is-soon');
    const inner =
      '<p class="mono contact-k">' + esc(c.k) + '</p>' +
      '<p class="contact-handle">' + esc(handle) + '</p>' +
      '<p class="contact-note">' + esc(c.note) + '</p>';
    if (c.hot) {
      // 韭菜群卡：点击打开入群弹窗（一步到位），不再跳转 X
      return '<div class="' + cls + '" data-group-open role="button" tabindex="0">' + inner + '</div>';
    }
    return (c.v && c.v.url)
      ? '<a class="' + cls + '" href="' + esc(c.v.url) + '"' +
          (c.v.url.startsWith('http') ? ' target="_blank" rel="noopener"' : '') + '>' + inner + '</a>'
      : '<div class="' + cls + '">' + inner + '</div>';
  }).join('');
})();

// 打赏
(function renderTips() {
  const root = document.querySelector('[data-tips-grid]');
  if (!root || !window.YZ_TIPS) { return; }

  const T = window.YZ_TIPS;
  const parts = [];

  [T.usdt, T.eth].forEach(function (t) {
    if (!t) { return; }
    parts.push(t.address
      ? '<button class="tip-item mono" type="button" data-copy="' + esc(t.address) + '">' +
          '<span class="tip-label">' + esc(t.label) + '</span>' +
          '<span class="tip-addr">' + esc(t.address) + '</span><span class="copy-hint">复制地址</span></button>'
      : '<div class="tip-item is-soon mono"><span class="tip-label">' + esc(t.label) + '</span><span class="gear-soon">整理中</span></div>');
  });

  [T.binance, T.okx].forEach(function (t) {
    if (!t) { return; }
    parts.push(t.url
      ? '<a class="tip-item mono" href="' + esc(t.url) + '" target="_blank" rel="noopener">' +
          '<span class="tip-label">' + esc(t.label) + '</span>' +
          (t.code ? '<span class="tip-addr">邀请码 ' + esc(t.code) + '</span>' : '') +
          '<span class="copy-hint">前往 →</span></a>'
      : '<div class="tip-item is-soon mono"><span class="tip-label">' + esc(t.label) + '</span><span class="gear-soon">整理中</span></div>');
  });

  root.innerHTML = parts.join('');
})();

// 一键复制（装备邀请码 + 打赏地址共用）
document.addEventListener('click', function (e) {
  const btn = e.target.closest('[data-copy]');
  if (!btn) { return; }
  e.preventDefault();

  navigator.clipboard.writeText(btn.dataset.copy).then(function () {
    const hint = btn.querySelector('.copy-hint');
    if (!hint) { return; }
    const old = hint.textContent;
    hint.textContent = '✓';
    btn.classList.add('copied');
    setTimeout(function () { hint.textContent = old; btn.classList.remove('copied'); }, 1600);
  }).catch(function () {
    window.prompt('手动复制：', btn.dataset.copy);
  });
});


/*── 8. 文章页分类筛选（与工具箱筛选相互独立）──*/

const wFilterBtns = [...document.querySelectorAll('[data-wfilter]')];
const wItems = [...document.querySelectorAll('[data-wcat]')];

wFilterBtns.forEach(function (btn) {
  btn.addEventListener('click', function () {
    wFilterBtns.forEach(function (b) { b.classList.toggle('active', b === btn); });
    const value = btn.dataset.wfilter;
    wItems.forEach(function (item) {
      item.classList.toggle('is-hidden', value !== '全部' && item.dataset.wcat !== value);
    });
  });
});


/*── 9. 航海播报：左舷轮播插槽 ──*/
/* 内容自动从站内收集：最新文章（文章页 DOM）、韭菜群（links.js）、
   NOW（关于页 DOM）、航海心得（links.js YZ_QUOTES）。 */

(function broadcast() {
  const box = document.querySelector('[data-broadcast]');
  const tagEl = document.querySelector('[data-bc-tag]');
  const textEl = document.querySelector('[data-bc-text]');
  const dotsEl = document.querySelector('[data-bc-dots]');
  if (!box || !tagEl || !textEl || !dotsEl) { return; }

  const items = [];

  // 最新文章（文章页第一张精选卡）
  const firstPost = document.querySelector('[data-page="writing"] .post[href]');
  if (firstPost) {
    items.push({
      tag: '新文章',
      text: firstPost.querySelector('h3').textContent,
      href: firstPost.getAttribute('href')
    });
  }

  // 韭菜群
  const g = window.YZ_CONTACT && window.YZ_CONTACT.group;
  if (g && g.url) {
    items.push({
      tag: '韭菜群 · ' + (g.price || ''),
      text: '一个同频小圈子，人满关门。微信 ' + (g.wechat || '') + ' 备注「' + (g.wechatNote || '进群') + '」',
      href: '#contact'
    });
  }

  // NOW · 在做
  const nowFirst = document.querySelector('[data-page="about"] .now-item p:last-child');
  if (nowFirst) {
    items.push({ tag: 'NOW · 在做', text: nowFirst.textContent, href: '#about' });
  }

  // 核心产品
  items.push({
    tag: '产品 · PAYWALLPRO',
    text: '别再凭感觉改付费墙——基于真实数据做订阅增长决策。',
    href: 'https://www.paywallpro.app'
  });

  // 航海心得（金句池随机抽两条，避免每次都一样）
  const quotes = (window.YZ_QUOTES || []).slice();
  for (let i = 0; i < 2 && quotes.length; i++) {
    const pick = quotes.splice((i * 2 + 1) % quotes.length, 1)[0];
    items.push({ tag: '航海心得', text: pick, href: '#about' });
  }

  if (!items.length) { return; }
  box.hidden = false;

  let current = 0;
  let timer = null;

  dotsEl.innerHTML = items.map(function (_, i) {
    return '<button type="button" role="tab" aria-label="第 ' + (i + 1) + ' 条播报"' +
           (i === 0 ? ' class="active"' : '') + ' data-bc-go="' + i + '"></button>';
  }).join('');

  function show(index) {
    current = (index + items.length) % items.length;
    const item = items[current];

    tagEl.textContent = item.tag;
    textEl.textContent = item.text;
    textEl.setAttribute('href', item.href);
    if (item.href.startsWith('http')) {
      textEl.setAttribute('target', '_blank');
      textEl.setAttribute('rel', 'noopener');
    } else {
      textEl.removeAttribute('target');
      textEl.removeAttribute('rel');
    }

    if (!reducedMotion) {
      textEl.classList.remove('bc-swap');
      void textEl.offsetWidth;
      textEl.classList.add('bc-swap');
    }

    [...dotsEl.children].forEach(function (d, i) {
      d.classList.toggle('active', i === current);
    });
  }

  function play() {
    if (reducedMotion || timer) { return; }
    timer = setInterval(function () { show(current + 1); }, 6000);
  }

  function pause() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  dotsEl.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-bc-go]');
    if (!btn) { return; }
    pause();
    show(parseInt(btn.dataset.bcGo, 10));
    play();
  });

  // 站内页签跳转：#about / #contact 走页签切换而非默认锚点
  textEl.addEventListener('click', function (e) {
    const href = this.getAttribute('href') || '';
    if (href.startsWith('#')) {
      e.preventDefault();
      showPage(href.slice(1), true);
    }
  });

  box.addEventListener('mouseenter', pause);
  box.addEventListener('mouseleave', play);

  show(0);
  play();
})();


/*── 10. 首屏 CTA：站内页签跳转 ──*/

document.querySelectorAll('[data-goto]').forEach(function (btn) {
  btn.addEventListener('click', function (e) {
    e.preventDefault();
    showPage(this.dataset.goto, true);
  });
});


/*── 11. 韭菜群弹窗：价格 + 介绍 + 三步入群，路径一步到位 ──*/

(function groupModal() {
  const g = window.YZ_CONTACT && window.YZ_CONTACT.group;
  if (!g || !g.wechat) { return; }

  const mask = document.createElement('div');
  mask.className = 'gm-mask';
  mask.setAttribute('data-gm', '');
  mask.innerHTML =
    '<div class="gm-modal" role="dialog" aria-label="加入韭菜群">' +
      '<button class="gm-close" data-gm-close aria-label="关闭">×</button>' +
      '<p class="gm-eyebrow mono">🌱 INNER CIRCLE · 同频小圈子</p>' +
      '<h3>' + esc(g.name || '韭菜群') + '</h3>' +
      '<p class="gm-price">¥99<small> / 一次付费 · 不是课程</small></p>' +
      '<p class="gm-note">' + esc(g.note || '') + '</p>' +
      '<div class="gm-body">' +
        '<ol class="gm-steps">' +
          '<li><span>加微信</span><b class="mono">' + esc(g.wechat) + '</b>' +
            '<button class="gm-copy" data-gm-copy>复制</button></li>' +
          '<li><span>备注</span><b>「' + esc(g.wechatNote || '进群') + '」</b>（不备注可能不通过）</li>' +
          '<li><span>通过后</span><b>微信转账 ¥99，</b>直接拉你进群</li>' +
        '</ol>' +
        '<div class="gm-qr">' +
          '<img src="./assets/images/wechat-qr.png?v=1" alt="鱼总微信二维码"' +
            ' onerror="this.closest(\'.gm-qr\').style.display=\'none\'">' +
          '<p>扫码直接加<br>手机可长按保存</p>' +
        '</div>' +
      '</div>' +
      (g.url ? '<a class="gm-link" href="' + esc(g.url) + '" target="_blank" rel="noopener">想先了解？看 X 上的完整介绍 ↗</a>' : '') +
      '<p class="gm-foot mono">人满关门 · 随时可退 · 不承诺任何收益</p>' +
    '</div>';
  document.body.appendChild(mask);

  function open() { mask.classList.add('show'); document.body.style.overflow = 'hidden'; }
  function close() { mask.classList.remove('show'); document.body.style.overflow = ''; }

  document.addEventListener('click', function (e) {
    const opener = e.target.closest('[data-group-open]');
    if (opener) { e.preventDefault(); open(); return; }
    if (e.target.closest('[data-gm-close]') || e.target === mask) { close(); return; }
    const copyBtn = e.target.closest('[data-gm-copy]');
    if (copyBtn) {
      const done = function () {
        copyBtn.textContent = '已复制 ✓';
        setTimeout(function () { copyBtn.textContent = '复制'; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(g.wechat).then(done).catch(function () { fallbackCopy(); });
      } else { fallbackCopy(); }
      function fallbackCopy() {
        const ta = document.createElement('textarea');
        ta.value = g.wechat;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); } catch (err) { /* 手动抄也行 */ }
        document.body.removeChild(ta);
      }
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { close(); }
  });
})();


/*── 11. 688 航线悬浮入口：显示航程进度 ──*/
(function () {
  const el = document.querySelector('[data-voyage-fab-progress]');
  if (!el) { return; }
  try {
    const summary = localStorage.getItem('yz-voyage-summary');
    const badge = localStorage.getItem('yz-voyage-badge');
    if (badge) { el.textContent = '🏅'; el.hidden = false; }
    else if (summary && summary !== '0/8') { el.textContent = summary; el.hidden = false; }
  } catch (e) { /* 隐私模式忽略 */ }
})();
