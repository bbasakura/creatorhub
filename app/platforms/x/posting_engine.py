"""X (Twitter) 自动化发帖引擎与 TopHub 题材库联动."""

import random
import re
import statistics
from collections import Counter
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional
from app.platforms.x.tophub_crawler import TopHubCrawler
from app.platforms.x.xbangdan_crawler import XBangDanCrawler

YESTERDAY_STYLE_SHORT_POSTS = [
    "今天没啥大道理。\n该干活干活，\n该摸鱼摸鱼。",
    "做号以后才发现：\n最难的不是发，\n是发完别一直盯数据。",
    "成年人恢复情绪最快的方法：\n先吃饭。\n别的吃饱再说。",
    "今天状态一般。\n但活还是得干。\n先把能做的做了。",
    "X 上混久了发现，\n能长期互相串门的人，\n比偶尔爆一条舒服多了。",
    "有时候不是想通了。\n只是懒得争了。",
    "别老等状态好。\n很多状态，\n都是干着干着才来的。",
    "今天目标很朴素：\n少刷一会儿，\n多做一点。",
    "做内容别太端着。\n人话，\n比正确的话好看。",
    "突然发现，\n最贵的不是时间，\n是被打断后重新进入状态。",
    "上班最魔幻的地方：\n忙一天，\n晚上想不起到底忙了啥。",
    "成年人所谓休息：\n换个地方继续看手机。",
    "今天谁还在更推？\n打个招呼，\n顺手认识几个新朋友。",
    "发帖这事，\n先发再说。\n别每条都想当代表作。",
    "做个人品牌最怕的不是没人看。\n是发两天没反馈，\n自己先跑了。",
    "有时候真不是自律。\n只是穷得比较清醒。",
    "一个小发现：\n越想把话说漂亮，\n越容易没人味。",
    "今天不讲方法论。\n就一句：\n能持续，比偶尔猛一下有用。",
    "网络上最舒服的关系：\n不查岗，不客套，\n看到就互相捧个场。",
    "别把每次低数据都当失败。\n有时候平台没看见，\n不代表人不行。",
    "想法太多的时候，\n先做最小的一件。\n脑子会安静很多。",
    "今天又学会一件事：\n别跟算法讲道理。",
    "有些事晚上想得很严重。\n睡一觉起来，\n也就那样。",
    "最真实的成长：\n以前想证明自己，\n现在只想把事做完。",
    "忙的时候总想休息。\n真闲下来，\n又开始心虚。",
    "能聊得来就多聊两句。\n聊不来就算了。\n互联网也不用硬社交。",
    "发完这条继续干活。\n今天不跟自己讲条件。",
    "有钱解决不了所有问题。\n但很多问题，\n确实可以先解决一半。",
    "今天的精神状态：\n脑子想下班，\n手还在敲键盘。",
    "别研究太久怎么开始。\n先把第一下做了。",
]

DEFAULT_SOCIAL_TAGS = ("浇朋友", "蓝朋友", "蓝V互关", "诚信互暖", "真诚交友", "蓝V互助")


TOPIC_TEMPLATES = [
    {
        "category": "pain_point",
        "templates": [
            (
                "讲个扎心真相：\n\n"
                "做内容最耗精力的不是写文案\n\n"
                "也不是做图做视频\n\n"
                "而是花了大半天做出来的东西\n\n"
                "数据还不如别人随手发的一句废话😂\n\n"
                "大家今天有被算法搞崩心态吗？"
            ),
            (
                "玩 X 最大的阳谋：\n\n"
                "明明知道每天都在给马斯克打工\n\n"
                "但每天一睁眼\n\n"
                "还是忍不住打开看通知红点\n\n"
                "你们每天在 X 上泡几个小时？"
            ),
            (
                "搞个人 IP 这段时间最大的体会：\n\n"
                "少看点宏大叙事的大道理\n\n"
                "多跟同频的人真诚聊几句\n\n"
                "走得反而比谁都踏实\n\n"
                "今天大家各自都在死磕什么项目？👇"
            ),
        ],
    },
    {
        "category": "poll_choice",
        "templates": [
            (
                "问大家一个很现实的问题：\n\n"
                "如果给你两个选择：\n"
                "A：一份月薪两万但眼见得到头的稳定工作\n"
                "B：全职做个人 IP 和自由职业，前半年可能一分不赚\n\n"
                "现在的你会怎么选？评论区蹲个真实想法👇"
            ),
            (
                "聊个创作工具习惯：\n\n"
                "身边做自媒体的朋友\n"
                "有人坚持纯手工写，觉得有灵魂\n"
                "有人全面上 AI 工具流，追求极致效率\n\n"
                "你们平时属于“纯手搓派”还是“工具流派”？"
            ),
            (
                "大城市还是老家？\n\n"
                "大城市机会多，但房租物价压力大\n"
                "小县城开销小安逸，但往往缺少好圈子\n\n"
                "如果重新给你一次选择的机会，你会留在哪？"
            ),
        ],
    },
    {
        "category": "hot_take",
        "templates": [
            (
                "一个可能得罪人的观点：\n\n"
                "90% 搞自媒体做不起来的人\n\n"
                "不是执行力不行，也不是懂的技术少\n\n"
                "而是姿态太高太端着了\n\n"
                "发的东西永远一股汇报味，没有半点人情味\n\n"
                "认同的扣个 1，不认同的欢迎来辩。"
            ),
            (
                "别被网上的“月入十万”带偏了节奏：\n\n"
                "普通人做个人品牌\n\n"
                "先把前 100 个真心愿意跟你互动的朋友维护好\n\n"
                "比什么虚头巴脑的爆款玄学都靠谱\n\n"
                "你目前在 X 上的核心好友有多少个了？"
            ),
        ],
    },
    {
        "category": "daily_greeting",
        "templates": [
            (
                "早！新的一天开工 ☕️\n\n"
                "今天给自己定了个小原则：\n"
                "少刷无关噪音，多做能产生复利的事\n\n"
                "大家的打工人状态上线了吗？打个卡互相打个气！"
            ),
            (
                "又到了每日下线休息时刻 🌙\n\n"
                "感谢今天所有点赞互动的好友\n"
                "明天继续满血搬砖！\n\n"
                "晚安各位，明天 9:00 不见不散 🤝"
            ),
        ],
    },
]

# 热点话题互动框架库（针对 TopHub 题材自动转化为 X 爆款）
HOT_TOPIC_FRAMEWORKS = {
    "tech_ai": [
        (
            "刚在热搜刷到这个：\n\n"
            "「{title}」\n\n"
            "技术和工具迭代的速度比想象中更快\n"
            "很多人还在观望\n"
            "头部团队早就闷头把应用跑通了\n\n"
            "普通人真没必要焦虑底层模型\n"
            "把手头用得顺的工具吃透才是硬道理\n\n"
            "这波大家怎么看？你们团队跟进了吗？👇"
        ),
        (
            "看到这个行业动态坐不住了：\n\n"
            "「{title}」\n\n"
            "信息差就是生产力\n"
            "同一波浪潮下：\n"
            "有人在当看客吃瓜\n"
            "有人已经拿到了第一波红利\n\n"
            "对这件事你持乐观还是悲观态度？\n"
            "评论区蹲几个行业同行的观点🔥"
        ),
        (
            "今天科技圈全在刷这个：\n\n"
            "「{title}」\n\n"
            "每次技术大洗牌\n"
            "最先被淘汰的从来不是不会工具的人\n"
            "而是思维固步自封的人\n\n"
            "如果换作你，会选择主动拥抱还是静观其变？\n"
            "扣个 1 拥抱，扣个 2 观望👇"
        ),
    ],
    "workplace_career": [
        (
            "知乎上这个话题今天直接爆了：\n\n"
            "「{title}」\n\n"
            "说句扎心的大实话：\n"
            "时代真的变了\n"
            "靠熬工龄和死工资的时代正在远去\n"
            "个人IP和可迁移能力才是最坚固的护城河\n\n"
            "如果再给你一次选择机会，你会怎么选？\n"
            "来评论区聊聊最真实的考量👇"
        ),
        (
            "看到这个现实话题很有感触：\n\n"
            "「{title}」\n\n"
            "成年人的世界没有容易二字\n"
            "很多时候选择往往比努力更残酷\n"
            "有人选择安逸，有人选择死磕折腾\n\n"
            "你们身边有类似的真实案例吗？\n"
            "最后结果都怎么样了？"
        ),
        (
            "热榜上都在讨论这个选择题：\n\n"
            "「{title}」\n\n"
            "现实总是很骨感：\n"
            "一边是看得见天花板的稳定\n"
            "一边是充满不确定性的自立门户\n\n"
            "现在的你更倾向哪一种生活状态？\n"
            "来听听大家的掏心窝子话👇"
        ),
    ],
    "hot_buzz": [
        (
            "全网都在热议这个事：\n\n"
            "「{title}」\n\n"
            "现在互联网的舆论风向真是瞬息万变\n"
            "表面看是热闹和吃瓜\n"
            "背后其实折射的是大家普遍的社会情绪\n\n"
            "大家怎么看待这件事？\n"
            "你站当事人还是站舆论这一边？👇"
        ),
        (
            "今天这个热点属实看笑了：\n\n"
            "「{title}」\n\n"
            "网友们的评论简直比正文还精彩😂\n"
            "只能说现在的消费者越来越不好糊弄了\n"
            "套路用多了，早晚会被反噬\n\n"
            "你们平时遇到过类似让人无语的坑吗？\n"
            "评论区一起吐槽排雷👇"
        ),
    ],
    "xbangdan": [
        (
            "今天在 X 上刷到这个爆款推文，深有感触：\n\n"
            "「{title}」\n\n"
            "在推特上做内容最核心的一点：\n"
            "真实的现场感和第一手信息永远跑赢二手搬运\n"
            "与其天天自嗨，不如多看看真正拿结果的人在聊什么\n\n"
            "大家平时在 X 上最爱看哪类内容？\n"
            "来评论区聊聊你们的关注偏好👇"
        ),
        (
            "看到这个高赞讨论，分享点个人思考：\n\n"
            "「{title}」\n\n"
            "很多时候爆款不是靠碰运气\n"
            "而是踩中了大家的真实痛点或情绪共鸣\n\n"
            "同行路上一起交流迭代\n"
            "对这个现象大家怎么看？欢迎一起探讨🔥"
        ),
    ],
}


def format_title_for_post(title: str, max_line_len: int = 28) -> str:
    """对热点标题进行智能呼吸感折行，确保单行不超标并保留语意."""
    title = title.strip()
    if len(title) <= max_line_len:
        return f"「{title}」"

    parts = []
    current = title
    while len(current) > max_line_len:
        split_idx = -1
        for punct in ["，", "、", "？", " ", "：", "；", "｜", "|", ";", ","]:
            idx = current.rfind(punct, 15, max_line_len)
            if idx > split_idx:
                split_idx = idx + 1
        if split_idx <= 0:
            split_idx = max_line_len
        parts.append(current[:split_idx].strip())
        current = current[split_idx:].strip()
    if current:
        parts.append(current)

    return "「" + "\n".join(parts) + "」"


class XPostingEngine:
    """X 自动化发帖引擎（支持原生模板与 TopHub 实时题材库联动）."""

    def __init__(
        self,
        crawler: Optional[TopHubCrawler] = None,
        xbangdan_crawler: Optional[XBangDanCrawler] = None,
    ):
        self.history: List[str] = []
        self.crawler = crawler or TopHubCrawler()
        self.xbangdan = xbangdan_crawler or XBangDanCrawler()

    def generate_post(self, category: Optional[str] = None) -> str:
        """从原生模板库生成日常推文."""
        available_categories = TOPIC_TEMPLATES
        if category:
            available_categories = [c for c in TOPIC_TEMPLATES if c["category"] == category]
            if not available_categories:
                available_categories = TOPIC_TEMPLATES

        chosen_group = random.choice(available_categories)
        candidates = chosen_group["templates"]
        unused = [c for c in candidates if c not in self.history[-5:]]
        post_text = random.choice(unused) if unused else random.choice(candidates)
        self.history.append(post_text)
        return post_text

    def generate_reference_style_post(
        self, reference_texts: Optional[List[str]] = None, rng=None
    ) -> str:
        """Generate one compact, conversational post shaped by recent real posts.

        Reference texts affect target length, hashtag choice, and similarity
        filtering. They are never copied verbatim.
        """
        rnd = rng or random
        refs = [str(text or "").strip() for text in (reference_texts or []) if str(text or "").strip()]
        lengths = [len(text) for text in refs]
        target_len = int(statistics.median(lengths)) if lengths else 58
        target_len = max(34, min(78, target_len))

        tags = Counter()
        for text in refs:
            tags.update(re.findall(r"#([^\s#]+)", text))
        popular_tags = [tag for tag, _count in tags.most_common(6)] or list(DEFAULT_SOCIAL_TAGS)

        def plain(text: str) -> str:
            value = re.sub(r"#[^\s#]+", "", text)
            return re.sub(r"\s+", "", value)

        recent_plain = [plain(text) for text in refs[:160]]
        candidates = []
        for body in YESTERDAY_STYLE_SHORT_POSTS:
            body_plain = plain(body)
            if any(
                SequenceMatcher(None, body_plain, old).ratio() >= 0.72
                for old in recent_plain if old
            ):
                continue
            candidates.append(body)
        if not candidates:
            candidates = list(YESTERDAY_STYLE_SHORT_POSTS)

        candidates.sort(key=lambda body: abs(len(body) - target_len))
        body = rnd.choice(candidates[: min(10, len(candidates))])

        roll = rnd.random()
        tag_count = 0 if roll < 0.25 else 1 if roll < 0.72 else 2
        chosen_tags = []
        if tag_count:
            unique_tags = list(dict.fromkeys(popular_tags))
            if len(unique_tags) >= tag_count:
                chosen_tags = rnd.sample(unique_tags, tag_count)
            else:
                chosen_tags = unique_tags
        text = body
        if chosen_tags:
            text += "\n\n" + " ".join(f"#{tag}" for tag in chosen_tags)

        # Stay close to yesterday's compact shape; never stretch a one-click
        # post into the long-form template style.
        if len(text) > 120:
            text = body
        validation = self.validate_post(text)
        if not validation["valid"]:
            raise ValueError(validation["reason"])
        self.history.append(text)
        return text

    def generate_post_from_topic(self, topic: Dict[str, Any]) -> str:
        """基于 TopHub 热点条目转换为符合 X 蓝V排版与互动规范的推文."""
        title = topic.get("title", "").strip()
        formatted_title = format_title_for_post(title)
        cat = "xbangdan" if topic.get("source") == "X榜单" else topic.get("category", "tech_ai")
        frameworks = HOT_TOPIC_FRAMEWORKS.get(cat, HOT_TOPIC_FRAMEWORKS["tech_ai"])
        template = random.choice(frameworks)

        post = template.replace("「{title}」", formatted_title).replace("{title}", formatted_title)
        self.history.append(post)
        return post

    def generate_hot_post(
        self, category: str = "tech_ai", prefer_x_native: bool = True
    ) -> Dict[str, Any]:
        """从题材库提取热门话题并生成推文卡片（支持 X 榜单原生与 TopHub）."""
        chosen_topic = None
        if prefer_x_native or category == "xbangdan":
            x_topics = self.xbangdan.get_viral_topics(limit=5)
            if x_topics:
                chosen_topic = random.choice(x_topics)

        if not chosen_topic:
            topics = self.crawler.get_topics_by_category(category=category, limit=10)
            if not topics:
                topics = self.crawler.fetch_topics()
            chosen_topic = random.choice(topics[:5]) if topics else {
                "title": "单月收入破千万，AI应用公司完成数千万元天使轮融资",
                "source": "36氪",
                "category": "tech_ai",
                "heat": "独家",
                "rank": 1,
                "link": "https://36kr.com",
            }

        post_text = self.generate_post_from_topic(chosen_topic)
        validation = self.validate_post(post_text)

        return {
            "post_text": post_text,
            "topic": chosen_topic,
            "valid": validation["valid"],
            "reason": validation["reason"],
            "character_count": len(post_text),
        }

    def recommend_daily_topics(
        self, limit: int = 5, include_x_native: bool = True
    ) -> List[Dict[str, Any]]:
        """为运营者智能推荐今日最适合发推的 Top N 题材与推文草稿."""
        selected_topics = []

        # 优先注入 X 榜单原生爆款题材
        if include_x_native:
            x_topics = self.xbangdan.get_viral_topics(limit=min(limit, 3))
            selected_topics.extend(x_topics)

        all_topics = self.crawler.fetch_topics()
        seen_sources = set(t.get("source") for t in selected_topics)
        for t in all_topics:
            src = t.get("source")
            if src not in seen_sources and len(t.get("title", "")) > 6:
                seen_sources.add(src)
                selected_topics.append(t)
            if len(selected_topics) >= limit:
                break

        results = []
        for t in selected_topics:
            post = self.generate_post_from_topic(t)
            val = self.validate_post(post)
            results.append({
                "source": t.get("source"),
                "rank": t.get("rank"),
                "heat": t.get("heat"),
                "title": t.get("title"),
                "category": t.get("category"),
                "post_draft": post,
                "valid": val["valid"],
            })
        return results

    @staticmethod
    def validate_post(text: str) -> Dict[str, Any]:
        """校验推文是否符合 X 平台呼吸感、长度与去 AI 味规范."""
        if not text or len(text.strip()) == 0:
            return {"valid": False, "reason": "推文内容为空"}
        if len(text) > 280:
            return {"valid": False, "reason": f"推文长度 {len(text)} 超过高互动推荐上限"}
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        for line in lines:
            if len(line) > 35:
                return {"valid": False, "reason": f"单行字数过长（{len(line)}字），破坏呼吸感排版"}
        forbidden_phrases = [
            "总而言之", "综上所述", "在这篇文章中", "作为一个AI", "深度解析如下", "值得注意的是",
            "首先", "其次", "最后但同样重要", "赋能", "让我们一起", "在这个时代", "不难发现",
        ]
        for phrase in forbidden_phrases:
            if phrase in text:
                return {"valid": False, "reason": f"命中 AI 腔禁忌词: {phrase}"}
        return {"valid": True, "reason": "校验通过"}
