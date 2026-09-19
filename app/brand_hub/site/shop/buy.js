'use strict';

/**
 * 下单页逻辑：表单校验 → /api/create-order → 渲染支付二维码 → 轮询支付状态
 */
(function () {
  var PRODUCT_ID = document.body.getAttribute('data-product-id');
  var UNIT_PRICE = parseInt(document.body.getAttribute('data-unit-price'), 10);
  var POLL_MS = 3000;

  var qty = 1;
  var pollTimer = null;
  var currentOrderId = null;

  var el = {
    price: document.querySelector('[data-price]'),
    total: document.querySelector('[data-total]'),
    modalAmount: document.querySelector('[data-modal-amount]'),
    name: document.querySelector('[data-buyer-name]'),
    phone: document.querySelector('[data-buyer-phone]'),
    prov: document.querySelector('[data-addr-prov]'),
    city: document.querySelector('[data-addr-city]'),
    area: document.querySelector('[data-addr-area]'),
    detail: document.querySelector('[data-addr-detail]'),
    note: document.querySelector('[data-buyer-note]'),
    agree: document.querySelector('[data-agree]'),
    submit: document.querySelector('[data-submit]'),
    err: document.querySelector('[data-form-err]'),
    mask: document.querySelector('[data-paymask]'),
    qrBox: document.querySelector('[data-pay-qr]'),
    orderNo: document.querySelector('[data-order-no]'),
    payStatus: document.querySelector('[data-pay-status]'),
    payClose: document.querySelector('[data-payclose]'),
    payMethods: document.querySelector('[data-pay-methods]'),
    payModal: document.querySelector('.pay-modal'),
    modalLabel: document.querySelector('.pay-modal .mono-label')
  };

  var payMethod = 'alipay';

  function refreshTotal() {
    var total = UNIT_PRICE * qty;
    el.total.textContent = '¥' + total;
    el.modalAmount.textContent = '¥' + total;
  }

  /* ── 数量步进器（1-10，可直接输入）── */
  var MAX_QTY = 10;
  var qtyInput = document.querySelector('[data-qty-input]');
  var qtyMinus = document.querySelector('[data-qty-minus]');
  var qtyPlus = document.querySelector('[data-qty-plus]');

  function setQty(n) {
    qty = Math.min(MAX_QTY, Math.max(1, n || 1));
    if (qtyInput) { qtyInput.value = qty; }
    if (qtyMinus) { qtyMinus.disabled = qty <= 1; }
    if (qtyPlus) { qtyPlus.disabled = qty >= MAX_QTY; }
    refreshTotal();
  }

  if (qtyMinus) { qtyMinus.addEventListener('click', function () { setQty(qty - 1); }); }
  if (qtyPlus) { qtyPlus.addEventListener('click', function () { setQty(qty + 1); }); }
  if (qtyInput) {
    qtyInput.addEventListener('input', function () {
      var v = parseInt(this.value.replace(/\D/g, ''), 10);
      if (v > 0) { setQty(v); }
    });
    qtyInput.addEventListener('blur', function () { setQty(parseInt(this.value, 10)); });
  }
  setQty(1);

  /* ── 省市区三级联动（数据来自 vendor/area-data.js，含直辖市二级结构）── */
  var AREAS = window.YZ_AREAS || [];

  function fillSelect(sel, names, placeholder) {
    sel.innerHTML = '<option value="">' + placeholder + '</option>' +
      names.map(function (n) { return '<option value="' + n + '">' + n + '</option>'; }).join('');
    sel.disabled = names.length === 0;
  }

  function currentProv() {
    return AREAS.filter(function (p) { return p[0] === el.prov.value; })[0] || null;
  }
  function currentCity() {
    var p = currentProv();
    if (!p) { return null; }
    return p[1].filter(function (c) { return c[0] === el.city.value; })[0] || null;
  }

  fillSelect(el.prov, AREAS.map(function (p) { return p[0]; }), '省份');

  // 直辖市（北京/上海/天津/重庆）只有两级：区县框整个隐藏，避免「点不了」的困惑
  function setAreaVisible(visible) {
    el.area.style.display = visible ? '' : 'none';
    el.area.parentElement.classList.toggle('two-cols', !visible);
  }

  el.prov.addEventListener('change', function () {
    var p = currentProv();
    var isMunicipality = p && p[1].length > 0 && p[1].every(function (c) { return c[1].length === 0; });
    fillSelect(el.city, p ? p[1].map(function (c) { return c[0]; }) : [], isMunicipality ? '区县' : '城市');
    fillSelect(el.area, [], '区县');
    el.area.disabled = true;
    setAreaVisible(!isMunicipality);
  });

  el.city.addEventListener('change', function () {
    var c = currentCity();
    var areas = c ? c[1] : [];
    fillSelect(el.area, areas, '区县');
    setAreaVisible(areas.length > 0);
  });

  function composeAddress() {
    var parts = [el.prov.value, el.city.value, el.area.value, el.detail.value.trim()];
    // 直辖市：省=市名，去重（北京市 北京市 → 北京市）
    if (parts[0] === parts[1]) { parts.splice(1, 1); }
    return parts.filter(Boolean).join(' ');
  }

  /* ── 表单本地缓存：误刷新/关页不丢内容（只存在买家自己的浏览器里）── */
  var FORM_KEY = 'yz-buy-form';

  function saveForm() {
    try {
      localStorage.setItem(FORM_KEY, JSON.stringify({
        name: el.name.value,
        phone: el.phone.value,
        prov: el.prov.value,
        city: el.city.value,
        area: el.area.value,
        detail: el.detail.value,
        note: el.note.value
      }));
    } catch (e) { /* 无痕模式等场景不可用，忽略 */ }
  }

  function restoreForm() {
    var saved;
    try { saved = JSON.parse(localStorage.getItem(FORM_KEY)); } catch (e) { return; }
    if (!saved) { return; }
    el.name.value = saved.name || '';
    el.phone.value = saved.phone || '';
    el.note.value = saved.note || '';
    el.detail.value = saved.detail || '';
    if (saved.prov) {
      el.prov.value = saved.prov;
      el.prov.dispatchEvent(new Event('change'));
      if (saved.city) {
        el.city.value = saved.city;
        el.city.dispatchEvent(new Event('change'));
        if (saved.area) { el.area.value = saved.area; }
      }
    }
    // 级联恢复过程中 change 事件会用中间态覆盖缓存，最后完整存一次
    saveForm();
  }

  [el.name, el.phone, el.detail, el.note].forEach(function (f) {
    f.addEventListener('input', saveForm);
  });
  [el.prov, el.city, el.area].forEach(function (f) {
    f.addEventListener('change', saveForm);
  });
  restoreForm();

  /* ── 支付方式切换 ── */
  if (els_payMethodsExists()) {
    el.payMethods.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-pay]');
      if (!btn) { return; }
      el.payMethods.querySelectorAll('[data-pay]').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      payMethod = btn.dataset.pay;
      el.submit.textContent = payMethod === 'wechat' ? '提交订单，微信扫码 →' : '提交订单，扫码支付 →';
    });
  }
  function els_payMethodsExists() { return !!el.payMethods; }

  /* ── 校验（与服务端规则一致）── */
  function validate() {
    if (el.agree && !el.agree.checked) {
      return '请先勾选确认已阅读「下单前必读」——里面有机型要求和使用限制，看完再买不踩坑';
    }
    var name = el.name.value.trim();
    var phone = el.phone.value.trim();
    if (name.length < 1 || name.length > 30) { return '请填写收件人姓名'; }
    if (!/^1[3-9]\d{9}$/.test(phone)) { return '请填写有效的 11 位手机号'; }
    if (!el.prov.value) { return '请选择省份'; }
    if (!el.city.value) { return '请选择城市'; }
    var c = currentCity();
    if (c && c[1].length > 0 && !el.area.value) { return '请选择区县'; }
    if (el.detail.value.trim().length < 4) { return '请填写详细地址（街道、小区、门牌号）'; }
    var address = composeAddress();
    if (address.length < 6 || address.length > 200) { return '收货地址过长或过短，请检查'; }
    return null;
  }

  function showErr(msg) {
    el.err.textContent = msg;
    el.err.style.display = msg ? 'block' : 'none';
  }

  /* ── 支付二维码渲染（本地生成，零外部依赖）── */
  function renderQr(text) {
    clearWxClaim();
    el.payStatus.classList.remove('wx-mode');
    el.modalLabel.textContent = 'ALIPAY · 扫码支付';
    el.qrBox.innerHTML = '';
    el.qrBox.classList.add('has-qr');
    var qr = qrcode(0, 'M');
    qr.addData(text);
    qr.make();
    var img = document.createElement('img');
    img.src = qr.createDataURL(5, 8);
    img.alt = '支付宝支付二维码';
    el.qrBox.appendChild(img);
  }

  function showFallback(orderId) {
    el.qrBox.innerHTML = '';
    el.qrBox.classList.add('has-qr');
    var p = document.createElement('p');
    p.className = 'qr-fallback';
    p.innerHTML = '订单已登记 ✓<br>支付通道即将开通<br>请通过 <a href="https://x.com/AI_Jasonyu" target="_blank" rel="noopener">X 私信鱼总</a> 完成付款<br>并附上订单号';
    el.qrBox.appendChild(p);
    setPayStatus('订单已创建，等待人工核付', false);
  }

  function setPayStatus(text, spinning) {
    el.payStatus.innerHTML = (spinning ? '<i></i>' : '') + text;
  }

  /* ── 微信收款码：静态码 + 买家自助认领 ── */
  function clearWxClaim() {
    var old = el.payModal.querySelector('.wx-claim');
    if (old) { old.remove(); }
  }

  function renderWechat(orderId, qrImage, amount, discountCents) {
    clearWxClaim();
    el.modalLabel.textContent = 'WECHAT PAY · 扫码支付';
    el.qrBox.innerHTML = '';
    el.qrBox.classList.add('has-qr');
    var img = document.createElement('img');
    img.src = qrImage;
    img.alt = '微信收款码';
    img.onerror = function () {
      el.qrBox.innerHTML = '<p class="qr-fallback">收款码加载失败<br>请 <a href="https://x.com/AI_Jasonyu" target="_blank" rel="noopener">X 私信鱼总</a> 获取</p>';
    };
    el.qrBox.appendChild(img);

    el.payStatus.classList.add('wx-mode');
    el.payStatus.innerHTML =
      '<b>请转账 ¥' + amount.toFixed(2) + '</b>' +
      '<span class="wx-note">' +
        (discountCents ? '已为你抹掉 ' + discountCents + ' 分零头 · ' : '') +
        '这个金额是本单唯一识别码，鱼总凭它对账，请勿改动<br>转完点下面按钮，到账后当天发货</span>';

    // 「我付好了」：仅用于页面流转，不推送打扰店主（到账以微信通知为准）
    var btn = document.createElement('button');
    btn.className = 'wx-claim';
    btn.type = 'button';
    btn.textContent = '我付好了，查看订单 →';
    btn.addEventListener('click', function () {
      btn.disabled = true;
      btn.textContent = '正在跳转…';
      fetch('/api/claim-paid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: orderId })
      }).catch(function () { /* 标记失败不影响买家流程 */ })
        .then(function () {
          location.href = './order.html?id=' + encodeURIComponent(orderId);
        });
    });
    el.payStatus.parentNode.insertBefore(btn, el.payClose);
  }

  /* ── 支付状态轮询 ── */
  function startPolling(orderId) {
    stopPolling();
    pollTimer = setInterval(function () {
      fetch('/api/order-status?id=' + encodeURIComponent(orderId))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.status && d.status !== 'pending') {
            stopPolling();
            setPayStatus('✓ 支付成功，正在跳转订单页…', false);
            setTimeout(function () {
              location.href = './order.html?id=' + encodeURIComponent(orderId);
            }, 1200);
          }
        })
        .catch(function () { /* 网络抖动，下轮重试 */ });
    }, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  /* ── 提交订单（网络闪断自动重试一次）── */
  function postOrder() {
    return fetch('/api/create-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_id: PRODUCT_ID,
        qty: qty,
        buyer_name: el.name.value.trim(),
        buyer_phone: el.phone.value.trim(),
        buyer_address: composeAddress(),
        buyer_note: el.note.value.trim(),
        pay_method: payMethod
      })
    }).then(function (r) {
      return r.json()
        .then(function (d) { return { ok: r.ok, data: d }; })
        .catch(function () { return { ok: false, data: { error: '服务器繁忙，请稍后重试' } }; });
    });
  }

  function resetSubmit() {
    el.submit.disabled = false;
    el.submit.textContent = payMethod === 'wechat' ? '提交订单，微信扫码 →' : '提交订单，扫码支付 →';
  }

  function submitOrder() {
    var msg = validate();
    if (msg) { showErr(msg); return; }
    showErr(null);

    el.submit.disabled = true;
    el.submit.textContent = '正在创建订单…';

    postOrder()
      .catch(function () {
        // 网络层失败（代理抖动/弱网）：1.5 秒后自动重试一次
        el.submit.textContent = '网络波动，自动重试中…';
        return new Promise(function (resolve) { setTimeout(resolve, 1500); }).then(postOrder);
      })
      .then(function (resp) {
        resetSubmit();
        if (!resp.ok) {
          showErr(resp.data.error || '下单失败，请稍后重试');
          return;
        }
        currentOrderId = resp.data.order_id;
        el.orderNo.textContent = '订单号 ' + currentOrderId;
        el.mask.classList.add('show');
        if (resp.data.pay_method === 'wechat') {
          el.modalAmount.textContent = '¥' + (resp.data.amount_cents / 100).toFixed(2);
          renderWechat(currentOrderId, resp.data.qr_image, resp.data.amount_cents / 100, resp.data.discount_cents || 0);
        } else if (resp.data.qr_code) {
          renderQr(resp.data.qr_code);
          setPayStatus('等待支付中，付款后自动跳转…', true);
          startPolling(currentOrderId);
        } else {
          showFallback(currentOrderId);
        }
      })
      .catch(function () {
        resetSubmit();
        showErr('网络异常，已自动重试仍未成功——请检查网络后再试，或挂/关代理切换网络环境');
      });
  }

  el.submit.addEventListener('click', submitOrder);

  el.payClose.addEventListener('click', function () {
    stopPolling();
    el.mask.classList.remove('show');
    if (currentOrderId) {
      // 关闭弹窗后仍可在订单页找回：给个入口提示
      showErr('订单 ' + currentOrderId + ' 已创建（未支付），可在「订单查询」中找回');
    }
  });

  /* ── 上架状态探测：后端 active=false 时把下单区换成预告 ── */
  (function checkAvailability() {
    fetch('/api/products')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.products) { return; }
        var p = d.products.filter(function (x) { return x.id === PRODUCT_ID; })[0];
        if (!p || p.active) { return; }
        renderComingSoon();
      })
      .catch(function () { /* 探测失败保持原样，下单时后端仍会拦截 */ });
  })();

  function renderComingSoon() {
    var card = el.submit.closest('.order-card');
    if (!card) { return; }
    card.innerHTML =
      '<h2>即将上架 <span class="mono">COMING SOON</span></h2>' +
      '<p class="cs-lede">这件还在备货，暂时下不了单。' +
      '想到货第一时间知道，去 X 关注我或直接私信说一声，我上架就 @ 你。</p>' +
      '<div class="cs-actions">' +
        '<a class="cs-btn" href="https://x.com/AI_Jasonyu" target="_blank" rel="noopener">到货提醒 · X 私信鱼总 →</a>' +
        '<a class="cs-ghost" href="../index.html">看看在售的商品</a>' +
      '</div>' +
      '<p class="order-tip">已上架的 ENC 美国卡是同类里最省心的选择，教程也都写好了。</p>';
  }

  // 勾选区的「下单前必读」链接：自动展开折叠块并滚动过去
  document.addEventListener('click', function (e) {
    var link = e.target.closest('[data-open-must]');
    if (!link) { return; }
    e.preventDefault();
    var fold = document.getElementById('fold-must');
    if (!fold) { return; }
    fold.open = true;
    fold.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  refreshTotal();
})();
