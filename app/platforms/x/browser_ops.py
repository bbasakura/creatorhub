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
        """生成在浏览器中安全回复某条推文的 JavaScript 执行代码"""
        return f"""
const replyText = {repr(reply_text)};
// 1. 找到回复输入框
const replyBox = document.querySelector('[data-testid="tweetTextarea_0"]') || document.querySelector('[role="textbox"]');
if (!replyBox) throw new Error("Reply textbox not found");

// 2. paste 注入
replyBox.focus();
const dt = new DataTransfer();
dt.setData('text/plain', replyText);
replyBox.dispatchEvent(new ClipboardEvent('paste', {{ bubbles: true, cancelable: true, clipboardData: dt }}));

// 3. 回读校验
await new Promise(r => setTimeout(r, 800));
const currentText = replyBox.innerText || replyBox.textContent || '';
if (!currentText.includes(replyText.slice(0, 5))) {{
  throw new Error("Text paste verification failed: " + currentText);
}}

// 4. 点击发送按钮
const sendBtn = document.querySelector('[data-testid="tweetButtonInline"]') || document.querySelector('[data-testid="tweetButton"]');
if (!sendBtn || sendBtn.getAttribute('aria-disabled') === 'true') {{
  throw new Error("Send button disabled or not found");
}}
sendBtn.click();
"""

    def get_post_workflow_code(self, post_text: str) -> str:
        """生成在浏览器中安全发布主帖的 JavaScript 执行代码"""
        return f"""
const postText = {repr(post_text)};
// 1. 找到发帖主输入框
const postBox = document.querySelector('[data-testid="tweetTextarea_0"]') || document.querySelector('[role="textbox"]');
if (!postBox) throw new Error("Post textbox not found");

// 2. paste 注入
postBox.focus();
const dt = new DataTransfer();
dt.setData('text/plain', postText);
postBox.dispatchEvent(new ClipboardEvent('paste', {{ bubbles: true, cancelable: true, clipboardData: dt }}));

// 3. 回读文本校验
await new Promise(r => setTimeout(r, 1000));
const currentText = postBox.innerText || postBox.textContent || '';
if (currentText.length < 5) {{
  throw new Error("Post text verification failed: length too short");
}}

// 4. 点击发送
const postBtn = document.querySelector('[data-testid="tweetButtonInline"]') || document.querySelector('[data-testid="tweetButton"]');
if (!postBtn || postBtn.getAttribute('aria-disabled') === 'true') {{
  throw new Error("Post button disabled or not found");
}}
postBtn.click();
"""
