# AGENTS.md — Personal Site

本文件继承仓库根目录 `AGENTS.md`，约束 canonical 个人站点 `app/brand_hub/site/`。

## 不变量

- 本目录是唯一 canonical 个人站点源码；不要再创建第二套 personal-website/yuzong_clone 平行实现。
- 静态页面不得写入账号 Token、私有 API 密钥或本机绝对路径。
- 修改导航、商店、汇款工具、voyage 等模块时保持现有 URL 与数据格式兼容，除非任务明确要求迁移。
- `tools/data/*.json` 必须保持合法 JSON；大型路线数据只做必要变更。
- 站点 JS 修改至少执行 `node --check`；路线 JSON 修改执行 JSON 解析验证。

## 主要入口

- `index.html`
- `server.js`
- `assets/js/script.js`
- `shop/`
- `tools/`
- `voyage/`
