"""X (Twitter) 飞书多维表格同步模块.

关联多维表格:
- App Token: FCLabM00oaErGAsXJ00cjkNjnJD
- Table ID (互动日志): tblIj4aDV3hO2A0x
- Table ID (推文备选题材库): tblDP1JFPjybcnMI
"""

import json
import time
import os
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

CFG_PATH = r"C:\Users\kk\.agents\skills\feishu-doc-1.2.7\config.json"
APP_TOKEN = "FCLabM00oaErGAsXJ00cjkNjnJD"
LOG_TABLE_ID = "tblIj4aDV3hO2A0x"
TOPIC_TABLE_ID = "tblDP1JFPjybcnMI"
BASE_URL = "https://open.feishu.cn/open-apis"


class XFeishuSync:
    """飞书多维表格同步器（支持互动日志与推文备选题材库）."""

    def __init__(
        self,
        cfg_path: str = CFG_PATH,
        app_token: str = APP_TOKEN,
        table_id: str = LOG_TABLE_ID,
        topic_table_id: str = TOPIC_TABLE_ID,
    ):
        self.cfg_path = cfg_path
        self.app_token = app_token
        self.table_id = table_id
        self.topic_table_id = topic_table_id
        self._tenant_token: Optional[str] = None
        self._token_expire_time: float = 0

    def _get_tenant_token(self) -> str:
        now = time.time()
        if self._tenant_token and now < self._token_expire_time:
            return self._tenant_token

        if not os.path.exists(self.cfg_path):
            raise FileNotFoundError(f"Feishu config file not found: {self.cfg_path}")

        with open(self.cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
        req_data = json.dumps({"app_id": cfg["app_id"], "app_secret": cfg["app_secret"]}).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})

        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get Feishu tenant token: {data}")

        self._tenant_token = data["tenant_access_token"]
        self._token_expire_time = now + data.get("expire", 7100) - 300
        return self._tenant_token

    def _api_request(self, path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token = self._get_tenant_token()
        url = f"{BASE_URL}{path}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        req_data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ==================== 互动日志表 (tblIj4aDV3hO2A0x) ====================

    def record_post(
        self,
        post_text: str,
        post_link: str = "",
        category: str = "",
        note: str = "",
        account_nick: str = "sakura",
        account_handle: str = "@sakurakk730",
    ) -> bool:
        now_ms = int(time.time() * 1000)
        handle = str(account_handle or "").strip()
        if handle and not handle.startswith("@"):
            handle = f"@{handle}"
        fields = {
            "日期": now_ms,
            "账号昵称": account_nick or handle or "X 账号",
            "Handle": handle or "—",
            "动作": ["发帖"],
            "留言内容": post_text,
            "回关": "—",
            "备注": f"[{category}] {note}".strip() if category else note,
        }
        if post_link:
            fields["帖子链接"] = {"link": post_link, "text": "推文链接"}

        res = self._api_request(
            f"/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records",
            method="POST",
            body={"fields": fields},
        )
        return res.get("code") == 0

    def record_reply(
        self,
        target_nick: str,
        target_handle: str,
        reply_text: str,
        tweet_link: str = "",
        actions: Optional[List[str]] = None,
        refollow_status: str = "—",
        note: str = "",
    ) -> bool:
        now_ms = int(time.time() * 1000)
        actions = actions or ["留言"]
        fields = {
            "日期": now_ms,
            "账号昵称": target_nick or target_handle,
            "Handle": target_handle if target_handle.startswith("@") else f"@{target_handle}",
            "动作": actions,
            "留言内容": reply_text,
            "回关": refollow_status,
            "备注": note,
        }
        if tweet_link:
            fields["帖子链接"] = {"link": tweet_link, "text": "帖子"}

        res = self._api_request(
            f"/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records",
            method="POST",
            body={"fields": fields},
        )
        return res.get("code") == 0

    def record_relationship(
        self,
        target_nick: str,
        target_handle: str,
        action: str,
        note: str = "",
    ) -> bool:
        """记录关注/取关成功动作到互动日志."""
        value = str(action or "").strip().lower()
        if value not in {"follow", "unfollow"}:
            raise ValueError("action must be follow or unfollow")
        label = "关注" if value == "follow" else "取关"
        return self.record_reply(
            target_nick=target_nick,
            target_handle=target_handle,
            reply_text=f"{label} {target_handle}".strip(),
            actions=[label],
            refollow_status="—",
            note=note,
        )

    # ==================== 推文备选题材库表 (tblDP1JFPjybcnMI) ====================

    def record_candidate_topic(
        self,
        title: str,
        source: str,
        category: str,
        rank: int = 0,
        heat: str = "",
        link: str = "",
        post_draft: str = "",
        status: str = "待选",
    ) -> bool:
        """单条写入备选题材库."""
        category_map = {
            "tech_ai": "科技/AI",
            "workplace_career": "职场/认知",
            "hot_buzz": "全网热议",
            "科技/AI": "科技/AI",
            "职场/认知": "职场/认知",
            "全网热议": "全网热议",
        }
        cat_name = category_map.get(category, "全网热议")
        now_ms = int(time.time() * 1000)

        fields: Dict[str, Any] = {
            "题材标题": title,
            "来源平台": source,
            "分类": cat_name,
            "榜单排名": rank,
            "热度值": heat or "—",
            "生成推文草稿": post_draft,
            "采纳状态": status,
            "收录时间": now_ms,
            "字数统计": len(post_draft) if post_draft else 0,
        }
        if link:
            fields["原文链接"] = {"link": link, "text": "查看热点"}

        res = self._api_request(
            f"/bitable/v1/apps/{self.app_token}/tables/{self.topic_table_id}/records",
            method="POST",
            body={"fields": fields},
        )
        return res.get("code") == 0

    def batch_record_candidate_topics(self, topic_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量同步备选题材入库 (飞书单批次最大支持 500 条，分批写入避免超出限制)."""
        category_map = {
            "tech_ai": "科技/AI",
            "workplace_career": "职场/认知",
            "hot_buzz": "全网热议",
            "科技/AI": "科技/AI",
            "职场/认知": "职场/认知",
            "全网热议": "全网热议",
        }
        now_ms = int(time.time() * 1000)

        records_payload = []
        for item in topic_items:
            cat_name = category_map.get(item.get("category", "hot_buzz"), "全网热议")
            post_draft = item.get("post_draft", "")
            fields: Dict[str, Any] = {
                "题材标题": item.get("title", ""),
                "来源平台": item.get("source", ""),
                "分类": cat_name,
                "榜单排名": item.get("rank", 0),
                "热度值": item.get("heat") or "—",
                "生成推文草稿": post_draft,
                "采纳状态": item.get("status", "待选"),
                "收录时间": now_ms,
                "字数统计": len(post_draft) if post_draft else 0,
            }
            link = item.get("link", "")
            if link:
                fields["原文链接"] = {"link": link, "text": "查看热点"}
            records_payload.append({"fields": fields})

        success_count = 0
        batch_size = 100
        for i in range(0, len(records_payload), batch_size):
            chunk = records_payload[i : i + batch_size]
            res = self._api_request(
                f"/bitable/v1/apps/{self.app_token}/tables/{self.topic_table_id}/records/batch_create",
                method="POST",
                body={"records": chunk},
            )
            if res.get("code") == 0:
                success_count += len(res.get("data", {}).get("records", []))
            else:
                print(f"[FeishuSync] 批量写入失败 chunk {i}: {res}")

        return {
            "total": len(topic_items),
            "synced": success_count,
            "success": success_count > 0,
        }

    def get_candidate_topics(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """获取题材库中的已有候选记录."""
        res = self._api_request(
            f"/bitable/v1/apps/{self.app_token}/tables/{self.topic_table_id}/records?page_size={page_size}"
        )
        if res.get("code") != 0:
            return []
        items = res.get("data", {}).get("items", [])
        return [
            {
                "record_id": it.get("record_id"),
                "fields": it.get("fields", {}),
            }
            for it in items
        ]

    def update_candidate_topic(self, record_id: str, fields: Dict[str, Any]) -> bool:
        """更新推文备选题材库单条记录."""
        res = self._api_request(
            f"/bitable/v1/apps/{self.app_token}/tables/{self.topic_table_id}/records/{record_id}",
            method="PUT",
            body={"fields": fields},
        )
        return res.get("code") == 0

    def update_candidate_status(self, record_id: str, status: str, tweet_link: str = "") -> bool:
        """更新题材采纳状态（如 '已采纳', '已发布', '弃用'）."""
        fields: Dict[str, Any] = {"采纳状态": status}
        if tweet_link:
            fields["原文链接"] = {"link": tweet_link, "text": "推文链接"}
        return self.update_candidate_topic(record_id, fields)

    def get_approved_topics(self, status: str = "已采纳", page_size: int = 100) -> List[Dict[str, Any]]:
        """获取所有已采纳（待发布）的推文题材."""
        records = self.get_candidate_topics(page_size=page_size)
        return [
            r for r in records
            if r.get("fields", {}).get("采纳状态") == status
        ]
