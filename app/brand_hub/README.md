# brand_hub

CreatorHub 的个人品牌与公开展示模块。

## 当前结构

- `site/`：当前 canonical 个人站点。源码来自原 `gpt-live/src/yuzong_clone/`；文本、JS/CSS、JSON 与必要图片资产已迁入。
- `github_profile/`：由原 `github-profile` 迁入的 README、HTML 预览、SVG 与设计说明。
- 原 `personal-website` Workspace 的实体目录已经不存在，因此没有另一套站点源码需要合并。

## 边界

这里负责个人主页、作品展示、公开内容与品牌资产；模型网关、实时语音和交易策略分别归 `model-gateway` 与 `trading-indicators`。

## 验收记录（2026-09-18）

- canonical site 的 server、主脚本、商店、汇款工具和 voyage JS 均通过 `node --check`。
- 大型 CSS 与原源码 SHA256 一致后再提升为 canonical。
- 站点所需 `avatar.jpg`、`og.png`、`wechat-qr.png` 已实体迁入。
