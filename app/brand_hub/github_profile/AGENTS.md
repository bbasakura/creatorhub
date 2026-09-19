# AGENTS.md — GitHub Profile 品牌模块

本文件继承仓库根目录 `AGENTS.md`，规则由原 `github-profile/AGENTS.md` 迁移并更新路径。

## 定位

维护 GitHub Profile README、SVG、HTML 预览和品牌设计说明。

## 不变量

- 严禁在公开 README、SVG、HTML 或截图中暴露私有 Token、Cookie、真实内部地址或其他敏感信息。
- 动态卡片、Badge 与外部图片必须考虑 GitHub CDN/camo 缓存和可用性；能本地化的核心品牌 SVG 优先本地化。
- 修改中英文 README 时保持主要信息一致，不允许一份长期漂移。
- 视觉改动先验证本地 HTML/SVG 预览，再同步公开版本。
- 本模块只是品牌资产，不承载账号调度、模型网关或交易逻辑。

## 关键入口

- `README.md` / `README.zh-CN.md`
- `preview*.html`
- `assets/`
- `docs/`
