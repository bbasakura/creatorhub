"""X (Twitter) 浏览器自动化操作模块.

核心能力:
1. 抓取「正在关注 / 蓝V好友」的实时推文流 (Home Timeline / Following Timeline).
2. 安全回复 (Reply): 点击 Reply -> paste 事件精准注入 -> 长度校验 -> 点击发送.
3. 安全发帖 (Post): 打开发帖框 -> paste 事件注入 -> textContent 校验 -> 点击发送.
4. 防风控与拟人化节奏: 随机延迟 (25~45s)，检测平台弹窗与限制信号.
"""

from typing import Dict, Any, List, Optional
from app.platforms.x.reply_engine import XReplyEngine
from app.platforms.x.posting_engine import XPostingEngine

# JavaScript 注入脚本代码段（供 Node REPL / Browser 使用）
JS_INJECT_PASTE = """
function pasteText(targetEl, text) {
  targetEl.focus();
  const dt = new DataTransfer();
  dt.setData('text/plain', text);
  const pasteEvent = new ClipboardEvent('paste', {
    bubbles: true,
    cancelable: true,
    clipboardData: dt
  });
  targetEl.dispatchEvent(pasteEvent);
}
"""

class XBrowserOps:
    """X 浏览器操作调度器"""

    def __init__(self):
        self.reply_engine = XReplyEngine()
        self.posting_engine = XPostingEngine()

    def get_reply_workflow_code(self, tweet_id: str, reply_text: str) -> str:
        """Legacy compatibility surface; direct browser writes are disabled."""
        return (
            'throw new Error("CreatorHub direct X reply injection is disabled; '
            'create a durable CommentTask draft and execute it through the task queue");'
        )

    def get_post_workflow_code(self, post_text: str) -> str:
        """Legacy compatibility surface; direct browser writes are disabled."""
        return (
            'throw new Error("CreatorHub direct X post injection is disabled; '
            'create a durable PublishTask draft and execute it through the task queue");'
        )
