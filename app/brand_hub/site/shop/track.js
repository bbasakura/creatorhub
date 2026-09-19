'use strict';

/**
 * 订单查询页逻辑：/api/order-status 查单 + 航行时间线渲染
 */
(function () {
  var el = {
    input: document.querySelector('[data-query-input]'),
    btn: document.querySelector('[data-query-btn]'),
    err: document.querySelector('[data-query-err]'),
    result: document.querySelector('[data-order-result]')
  };

  var STEP_ORDER = ['pending', 'paid', 'shipped', 'done'];
  var STEP_LABEL = {
    pending: '已下单 —— 等待付款',
    paid: '已付款 —— 鱼总备货中',
    shipped: '已发货 —— 快递单号见上方',
    done: '确认收货 · 完成'
  };

  function fmtTime(iso) {
    if (!iso) { return '——'; }
    var d = new Date(iso);
    var pad = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function showErr(msg) {
    el.err.textContent = msg || '';
    el.err.style.display = msg ? 'block' : 'none';
    if (msg) { el.result.style.display = 'none'; }
  }

  function esc(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  function render(o) {
    var stepIdx = STEP_ORDER.indexOf(o.status);
    var timeline;

    if (o.status === 'closed') {
      timeline = '<div class="or-step done"><p class="t">' + esc(fmtTime(o.created_at)) + '</p><p class="s">已下单</p></div>' +
        '<div class="or-step cur"><p class="t">——</p><p class="s">订单已关闭（超时未付款或已退款）</p></div>';
    } else {
      timeline = STEP_ORDER.map(function (step, i) {
        var cls = i < stepIdx ? 'done' : (i === stepIdx ? 'cur' : '');
        var t = '——';
        if (step === 'pending') { t = fmtTime(o.created_at); }
        if (step === 'paid' && o.paid_at) { t = fmtTime(o.paid_at); }
        return '<div class="or-step ' + cls + '"><p class="t">' + esc(t) + '</p><p class="s">' + STEP_LABEL[step] + '</p></div>';
      }).join('');
    }

    el.result.innerHTML =
      '<div class="or-head">' +
        '<span class="no">订单 ' + esc(o.order_id) + '</span>' +
        '<span class="or-status">' + esc(o.status_text) + '</span>' +
      '</div>' +
      '<div class="or-body">' +
        '<span>商品：<b>' + esc(o.product) + ' × ' + esc(o.qty) + '</b></span>' +
        '<span>金额：<b>¥' + (o.amount_cents / 100).toFixed(2) + '</b> · ' + (o.pay_method === 'wechat' ? '微信支付' : '支付宝') + '</span>' +
        (o.tracking_no ? '<span>快递：<b>' + esc(o.tracking_no) + '</b></span>' : '') +
      '</div>' +
      '<div class="or-timeline">' + timeline + '</div>' +
      claimBox(o);
    el.result.style.display = 'block';
    bindClaim(o);
  }

  /** 微信订单且未认领：提供补交「我已付款」的入口 */
  function claimBox(o) {
    if (o.pay_method !== 'wechat' || o.status !== 'pending' || o.claim_pending) { return ''; }
    return '<div class="or-claim">' +
      '<p class="oc-title">还没付款？</p>' +
      '<p class="oc-note">扫码转账 <b>¥' + (o.amount_cents / 100).toFixed(2) + '</b>（金额一分不能差，尾数是这单的识别码）。' +
      '鱼总收到到账通知后会核对发货，通常当天完成。</p>' +
      '<button class="oc-btn" type="button" data-claim-btn>我已完成付款</button>' +
      '</div>';
  }

  function bindClaim(o) {
    var btn = el.result.querySelector('[data-claim-btn]');
    if (!btn) { return; }
    btn.addEventListener('click', function () {
      btn.disabled = true;
      btn.textContent = '已记录，等待核实…';
      fetch('/api/claim-paid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: o.order_id })
      }).catch(function () { /* 不影响买家 */ })
        .then(function () { btn.textContent = '✓ 已记录，鱼总核实中'; });
    });
  }

  function query() {
    var id = el.input.value.trim().toUpperCase();
    if (!/^YZ[0-9A-Z]{10,24}$/.test(id)) {
      showErr('请输入正确的订单号（YZ 开头，下单成功时展示过，也在支付页可复制）');
      return;
    }
    showErr(null);
    el.btn.disabled = true;
    el.btn.textContent = '查询中…';

    fetch('/api/order-status?id=' + encodeURIComponent(id))
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (resp) {
        el.btn.disabled = false;
        el.btn.textContent = '查询';
        if (!resp.ok) { showErr(resp.data.error || '查询失败，请稍后重试'); return; }
        render(resp.data);
      })
      .catch(function () {
        el.btn.disabled = false;
        el.btn.textContent = '查询';
        showErr('网络异常，请稍后重试');
      });
  }

  el.btn.addEventListener('click', query);
  el.input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { query(); }
  });

  // 支付成功跳转带 ?id=：自动查询
  var params = new URLSearchParams(location.search);
  var fromUrl = (params.get('id') || '').trim();
  if (fromUrl) {
    el.input.value = fromUrl;
    query();
  }
})();
