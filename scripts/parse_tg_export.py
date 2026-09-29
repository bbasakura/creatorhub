import argparse
import glob
import os
import re
from datetime import datetime
from typing import Dict, List, Set, Tuple
from bs4 import BeautifulSoup
import pandas as pd

EXCLUDE_HANDLES = {
    'home', 'explore', 'notifications', 'messages', 'i', 'settings',
    'search', 'hashtag', 'login', 'signup', 'intent', 'share', 'privacy', 'tos'
}

MUTUAL_KEYWORDS = [
    '互关', '互粉', '互推', '回关', '必回', '秒回',
    '互fo', '互关注', '关注', '关了', '回了'
]


def file_sort_key(file_path: str) -> int:
    fname = os.path.basename(file_path)
    match = re.search(r'messages(\d+)?\.html', fname)
    if not match or not match.group(1):
        return 1
    return int(match.group(1))


def parse_tg_date(date_str: str) -> datetime:
    try:
        clean = str(date_str).split(' UTC')[0].strip()
        return datetime.strptime(clean, '%d.%m.%Y %H:%M:%S')
    except Exception:
        return datetime.min


def parse_chat_export_directory(dir_path: str) -> Tuple[str, List[Dict]]:
    html_files = sorted(glob.glob(os.path.join(dir_path, "messages*.html")), key=file_sort_key)
    if not html_files:
        return "", []

    group_name = "未命名群聊"
    with open(html_files[0], 'r', encoding='utf-8') as f:
        soup_head = BeautifulSoup(f.read(25000), 'html.parser')
        header_tag = soup_head.find('div', class_='page_header')
        if header_tag:
            group_name = header_tag.get_text(strip=True)

    records: List[Dict] = []
    extra_handles: Dict[str, Dict] = {}

    for fpath in html_files:
        with open(fpath, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
            msgs = soup.find_all('div', class_=lambda c: c and 'message' in c and 'default' in c)

            for m in msgs:
                from_tag = m.find('div', class_='from_name')
                from_name = from_tag.get_text(strip=True) if from_tag else ''

                text_tag = m.find('div', class_='text')
                if not text_tag:
                    continue
                text = text_tag.get_text(separator=' ', strip=True)

                date_tag = m.find('div', class_='date')
                date_str = date_tag.get('title', '') if date_tag else ''

                a_tags = text_tag.find_all('a')
                urls = [a.get('href', '') for a in a_tags if a.get('href')]
                raw_urls = re.findall(r'https?://[^\s<>"\'()]+', text)
                combined_urls = list(set(urls + raw_urls))

                has_x_link = False
                for u in combined_urls:
                    u_lower = u.lower()
                    if 'x.com' in u_lower or 'twitter.com' in u_lower:
                        clean_u = u.split('?')[0].split('#')[0].rstrip('/')
                        m_profile = re.search(
                            r'(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,30})(?:/status/\d+)?',
                            clean_u, re.I
                        )
                        if m_profile:
                            handle = m_profile.group(1)
                            if handle.lower() not in EXCLUDE_HANDLES:
                                has_x_link = True
                                records.append({
                                    'handle': handle,
                                    'handle_lower': handle.lower(),
                                    'profile_url': f'https://x.com/{handle}',
                                    'from_tg_user': from_name,
                                    'date': date_str,
                                    'text': text
                                })

                if not has_x_link and any(k in text.lower() for k in MUTUAL_KEYWORDS):
                    handles = re.findall(r'@([A-Za-z0-9_]{3,30})', text)
                    for h in handles:
                        hl = h.lower()
                        if hl not in EXCLUDE_HANDLES and hl not in {'ka120120'}:
                            if hl not in extra_handles:
                                extra_handles[hl] = {
                                    'handle': h,
                                    'handle_lower': hl,
                                    'profile_url': f'https://x.com/{h}',
                                    'from_tg_user': from_name,
                                    'date': date_str,
                                    'text': text
                                }

    profiles: Dict[str, Dict] = {}
    for r in records:
        h = r['handle_lower']
        if h not in profiles:
            profiles[h] = {
                '推特Handle': f"@{r['handle']}",
                '推特主页链接': r['profile_url'],
                'TG群发言人': set([r['from_tg_user']]),
                '首次出现时间': r['date'],
                '最近活跃时间': r['date'],
                '在群出现次数': 1,
                '互关发言内容': r['text'][:150],
                '账号来源类型': '完整X主页链接',
                '群聊来源': group_name,
                '关注状态(自用备注)': ''
            }
        else:
            p = profiles[h]
            p['TG群发言人'].add(r['from_tg_user'])
            p['最近活跃时间'] = r['date']
            p['在群出现次数'] += 1
            if any(k in r['text'] for k in ['互关', '互粉', '回关', '必回', '秒回', '诚信']):
                p['互关发言内容'] = r['text'][:150]

    for hl, item in extra_handles.items():
        if hl not in profiles:
            profiles[hl] = {
                '推特Handle': f"@{item['handle']}",
                '推特主页链接': item['profile_url'],
                'TG群发言人': set([item['from_tg_user']]),
                '首次出现时间': item['date'],
                '最近活跃时间': item['date'],
                '在群出现次数': 1,
                '互关发言内容': item['text'][:150],
                '账号来源类型': '纯文本@Handle提及',
                '群聊来源': group_name,
                '关注状态(自用备注)': ''
            }

    parsed_list = list(profiles.values())
    for item in parsed_list:
        item['TG群发言人'] = ' / '.join([n for n in item['TG群发言人'] if n])

    parsed_list.sort(key=lambda x: (parse_tg_date(x['最近活跃时间']), x['在群出现次数']), reverse=True)
    return group_name, parsed_list


def main():
    parser = argparse.ArgumentParser(description="Telegram群聊导出文件提取X互关目标账号")
    parser.add_argument("--dir", type=str, help="单个导出目录路径")
    parser.add_argument("--all-dirs", type=str, help="包含多个ChatExport_*的父目录路径")
    parser.add_argument("--out-dir", type=str, default="", help="输出结果目录(默认保存在原导出目录)")
    args = parser.parse_args()

    targets = []
    if args.dir:
        targets.append(os.path.abspath(args.dir))
    elif args.all_dirs:
        parent = os.path.abspath(args.all_dirs)
        dirs = [
            os.path.join(parent, d) for d in os.listdir(parent)
            if os.path.isdir(os.path.join(parent, d)) and d.startswith("ChatExport_")
        ]
        targets.extend(sorted(dirs))
    else:
        print("请指定 --dir 或 --all-dirs 参数。")
        return

    all_master_profiles: Dict[str, Dict] = {}

    for t_dir in targets:
        print(f"正在解析: {t_dir}")
        gname, items = parse_chat_export_directory(t_dir)
        print(f"  群名称: {gname}, 提取有效互关账号: {len(items)} 个")

        if items:
            df_group = pd.DataFrame(items)
            out_base = args.out_dir if args.out_dir else t_dir
            safe_name = re.sub(r'[\\/:*?"<>|]', '_', gname)
            out_excel = os.path.join(out_base, f"X_互关目标清单_{safe_name}_{len(items)}人.xlsx")
            out_csv = os.path.join(out_base, f"X_互关目标清单_{safe_name}_{len(items)}人.csv")
            df_group.to_excel(out_excel, index=False)
            df_group.to_csv(out_csv, index=False, encoding='utf-8-sig')

            for r in items:
                h = str(r['推特Handle']).lower()
                if h in all_master_profiles:
                    curr = all_master_profiles[h]
                    if gname not in curr['群聊来源']:
                        curr['群聊来源'] += f" + {gname}"
                    if parse_tg_date(r['最近活跃时间']) > parse_tg_date(curr['最近活跃时间']):
                        curr['最近活跃时间'] = r['最近活跃时间']
                        curr['互关发言内容'] = r['互关发言内容']
                    curr['在群出现次数'] += r['在群出现次数']
                else:
                    all_master_profiles[h] = dict(r)

    if len(targets) > 1 and all_master_profiles:
        master_list = list(all_master_profiles.values())
        master_list.sort(key=lambda x: (parse_tg_date(x['最近活跃时间']), x['在群出现次数']), reverse=True)
        master_df = pd.DataFrame(master_list)
        
        out_base = args.out_dir if args.out_dir else targets[0]
        m_excel = os.path.join(out_base, f"X_多群互关总汇清单_去重共{len(master_df)}人.xlsx")
        m_csv = os.path.join(out_base, f"X_多群互关总汇清单_去重共{len(master_df)}人.csv")
        master_df.to_excel(m_excel, index=False)
        master_df.to_csv(m_csv, index=False, encoding='utf-8-sig')
        print(f"\n跨群去重总汇完成，共计 {len(master_df)} 人。")
        print(f"总汇文件保存在: {m_excel}")


if __name__ == "__main__":
    main()

