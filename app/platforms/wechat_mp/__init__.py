"""微信公众平台 (WeChat Official Account / wechat_mp) 平台包。

提供：
1. 账号资料解析 (parse_self_user)；
2. 文章/草稿/贴图解析 (parse_mp_feed) 与留言解析 (parse_mp_comment, flatten_mp_comments)；
3. ID 与文章链接解析 (resolve_mp_user_id, resolve_mp_article_id, looks_like_article)；
4. 综合发布引擎 (publish_mp - 支持图文草稿/图片贴图/视频消息/无推送发表)。
"""
from .extract import (parse_mp_feed, parse_mp_comment,
                      flatten_mp_comments, parse_self_user,
                      safe_title, Aweme, MediaItem)
from .resolve import (resolve_mp_user_id, resolve_mp_article_id,
                      looks_like_article)
from .publish import publish_mp

__all__ = [
    "parse_mp_feed", "parse_mp_comment", "flatten_mp_comments",
    "parse_self_user", "safe_title", "Aweme", "MediaItem",
    "resolve_mp_user_id", "resolve_mp_article_id", "looks_like_article",
    "publish_mp",
]

