'use strict';

/**
 * ═══════════════════════════════════════════════════
 *  鱼总的链接配置中心 —— 全站唯一需要手填的文件
 * ═══════════════════════════════════════════════════
 *  规则：
 *  - url 留空 '' = 该卡片显示「整理中」，不出现死链
 *  - code 留空 '' = 不显示邀请码芯片
 *  - 填好保存刷新即生效，其他文件都不用动
 */

/* ── 联系方式 ── */
window.YZ_CONTACT = {
  x:        { handle: '@AI_Jasonyu',  url: 'https://x.com/AI_Jasonyu' },
  telegram: { handle: '',             url: '' },   // 个人 TG，例：@yuzongAI
  wechat:   { handle: '鱼总聊AI',      url: '' },   // 公众号（可留空 url）
  mail:     { handle: 'hi@yuzong.ai', url: 'mailto:hi@yuzong.ai' },
  github:   { handle: 'jasonyu217',   url: 'https://github.com/jasonyu217' },

  /* 韭菜群：99 元一次性付费微信群（不是课程、不承诺交付、人满关门、随时可退）
     卡片点击 → 打开 X 上的完整介绍文章；入群 = 加微信并备注 */
  group: {
    name: '韭菜群',
    price: '¥99 · 一次',
    wechat: 'jasonyu110',
    wechatNote: '鱼总朋友 VX 群',      // 加微信时的备注
    url: 'https://x.com/AI_Jasonyu/status/2072277885168033834',  // 完整介绍（置顶推）
    note: '同频小圈子，不是课程：真实思路、公域不便发的东西、偶尔线下。人满关门，随时可退。'
  }
};

/* ── 航海心得：左侧「航海播报」轮播的金句池，可自行增删 ── */
window.YZ_QUOTES = [
  '团队不一定放大你，可能先放大你的开销。',
  '没有存款也能创业——把成本降到 688 元就行。',
  '自媒体涨粉 10 万，不如一个跑通的产品踏实。',
  '「网站」这个旧产物，在海外依然生机勃勃。'
];

/* ── 打赏 / 请我喝咖啡 ── */
window.YZ_TIPS = {
  usdt:    { label: 'USDT · TRC20', address: '' },   // 填钱包地址
  eth:     { label: 'ETH · ERC20',  address: '' },
  binance: { label: '币安注册',      url: '', code: '' },
  okx:     { label: 'OKX 注册',      url: '', code: '' }
};

/* ── 出海装备（含邀请码返佣）── */
window.YZ_GEAR = [
  {
    section: '写卡器 · 让国行手机用上 eSIM',
    no: '03-A',
    items: [
      { name: 'XeSIM X2 Pro', tag: 'iPhone 首选', hot: true,
        desc: 'Seed Link 自带联网，iPhone 直接写卡不求人——我的主力卡，存了六七张号没翻过车。约 $36，别买 X1。',
        url: 'https://xesim.cc/?DIST=T0VCGw%3D%3D', code: 'JUST10', deal: '9 折' },
      { name: 'BeeSIM 蓝牙工具卡', tag: '国行 iPhone', hot: true,
        desc: '超雪团队出品，内置蓝牙免读卡器，微信小程序写卡，国行 iPhone 插卡即用。淘宝搜口令领 ¥20 券。',
        url: 'https://s.tb.cn/c.0xH4jJ', code: '53642600', deal: '券后 ¥109' },
      { name: '9eSIM V3', tag: '安卓性价比',
        desc: '1.5M 空间存 50 张卡，仓鼠党唯一选择；iPhone 上只能切换不能写入。约 $24。',
        url: 'https://www.9esim.com/?coupon=yuzong', code: 'YUZONG' },
      { name: 'ESTK', tag: '极客之选',
        desc: 'Bootstrap 自带流量、开源生态活跃，Max 版 60 张容量，爱折腾选它。',
        url: 'https://store.estk.me/', code: 'YUZONG', deal: '9 折' },
      { name: '写卡器保姆级指南（五款横评）', tag: '教程',
        desc: '全部自费购入、实测一个多月写出的对比——谁值得买、谁是智商税，一目了然。',
        url: './posts/esim-writer-guide.html', code: '' }
    ]
  },
  {
    section: '保号卡 · 一个属于你的海外号码',
    no: '03-B',
    items: [
      { name: 'ENC 美国卡（T-Mobile）', tag: '自营现货', hot: true,
        desc: '真实 +1 号码非 VoIP，美区注册与长期保号之选——杂货铺现货，支付宝下单当天发。¥158。',
        url: './shop/enc-tmobile/', code: '' },
      { name: 'Saily 美国号', tag: '低成本保号',
        desc: 'Nord 旗下真实蜂窝号：首月 $0.98、月租 $0.99，收短信免费。配 BeeSIM 国行 iPhone 可用，保姆级教程已出。',
        url: 'https://x.com/AI_Jasonyu/status/2080877134319624492', code: 'ZHIKUI8049', deal: '立减 $5' },
      { name: 'Giffgaff 英国卡', tag: '英国 +44',
        desc: '一次充值理论保号 60 年，ChatGPT 接码稳。保姆级教程已备好，现货即将上架杂货铺。',
        url: './posts/giffgaff-guide.html', code: '' },
      { name: '香港 Club Sim', tag: '香港 +852',
        desc: '免月租香港号，接码保号轻量之选，也是港卡银行开户的敲门砖。',
        url: '', code: '' },
      { name: '德国沃达丰', tag: '欧盟 +49',
        desc: '德国实体号，注册欧洲区服务用。办理门槛一直在提高，办卡要趁早。',
        url: '', code: '' },
      { name: '荷兰沃达丰', tag: '欧盟 +31',
        desc: '欧洲保号的另一个选择，适合搭欧区账号矩阵。',
        url: '', code: '' }
    ]
  },
  {
    section: 'eSIM 流量 · 落地即有网',
    no: '03-C',
    items: [
      { name: 'Eskimo', tag: '送流量', hot: true,
        desc: '多国流量 eSIM 平台，注册用礼包码免费领 1GB 全球流量（2 年有效），配合写卡器即插即用。',
        url: 'https://eskimo.onelink.me/OsvZ/redeem', code: 'YUZONG', deal: '免费 1GB' }
    ]
  },
  {
    section: '金融账户',
    no: '03-D',
    items: [
      { name: 'StarryBlue U 卡', tag: 'U 卡', hot: true,
        desc: '加密资产日常消费的过渡方案——海外订阅、绑卡支付都好使，注册教程已出。',
        url: 'https://x.com/AI_Jasonyu/status/2087182339080172010', code: 'MHQK01I' },
      { name: '香港银行户口', tag: '银行',
        desc: '出海资金中转站：收美金、买港美股、办卡都从这里开始。开户攻略整理中。',
        url: '', code: '' },
      { name: '港美股券商', tag: '投资',
        desc: '开户入金指南 + 我在用的券商，新客通常有开户奖励。',
        url: '', code: '' },
      { name: 'Web3 交易所', tag: '加密',
        desc: '币安 / OKX 注册通道，手续费返佣路线。',
        url: '', code: '' }
    ]
  },
  {
    section: '企业与开发',
    no: '03-E',
    items: [
      { name: '海外公司注册', tag: '企业',
        desc: '美国 / 香港公司注册，App 上架和收款的合规底座。',
        url: '', code: '' },
      { name: '海外支付平台', tag: '收款',
        desc: 'Stripe、Paddle、LemonSqueezy——独立开发者的收款方案对比。',
        url: '', code: '' },
      { name: '开发者基建', tag: '开发',
        desc: '域名、服务器、部署平台，我自己项目在用的一套。',
        url: '', code: '' }
    ]
  }
];
