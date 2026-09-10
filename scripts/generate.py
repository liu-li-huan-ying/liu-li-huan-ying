#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GitHub 主页 README —— 所有卡片均为自制内联 SVG，零外部依赖。

用法:
    python scripts/generate.py            # 需要 gh 已登录（或设置 GITHUB_TOKEN）
输出:
    README.md     由 template.md 注入 SVG 后生成
    preview.html  本地预览用（把 SVG 片段拼进深色页面）
"""

import json
import os
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 配置

USER = "liu-li-huan-ying"
W = 800  # SVG 基准宽度（GitHub 主页内容列宽度内安全值）

C_BG = "#0D1117"
C_CARD = "#161B22"
C_BORDER = "#30363D"
C_TEXT = "#E6EDF3"
C_MUTED = "#8B949E"
C_DIM = "#6E7681"

# 霓虹渐变三色（紫 → 粉 → 青）
NEON = ["#A855F7", "#EC4899", "#06B6D4"]

SANS = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
    "'Hiragino Sans GB','Microsoft YaHei',sans-serif"
)
MONO = "'SFMono-Regular',Consolas,'Cascadia Code','Liberation Mono',monospace"

# 语言配色（GitHub 官方语言色）
LANG_COLORS = {
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Vue": "#41b883",
    "Go": "#00ADD8", "C++": "#f34b7d", "Rust": "#dea584", "Python": "#3572A5",
    "HTML": "#e34c26", "CSS": "#563d7c", "Java": "#b07219", "C": "#555555",
    "Shell": "#89e051", "Ruby": "#701516", "PHP": "#4F5D95", "Swift": "#F05138",
    "Kotlin": "#A97BFF", "Dart": "#00B4AB", "Lua": "#000080", "Makefile": "#427819",
    "CMake": "#DA3434", "C#": "#178600", "SCSS": "#c6538c", "MDX": "#fcb32c",
}
FALLBACK_COLOR = "#8B949E"

# 技能 chips（改这里即可）
SKILLS = [
    "JavaScript", "TypeScript", "Vue 3", "React Native", "Node.js",
    "Go", "C++", "Rust", "HTML / CSS", "Git",
    "Docker", "Linux", "Chrome 扩展", "Obsidian 插件",
]

TZ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- 工具

def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def get_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("PAT")
    if tok:
        return tok.strip()
    try:
        return subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=20
        ).stdout.strip()
    except Exception:
        return ""


def api_get(url: str, token: str):
    req = urllib.request.Request(url, headers={
        "Authorization": "token " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-readme-gen",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def api_graphql(query: str, variables: dict, token: str):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": "token " + token,
                 "Content-Type": "application/json",
                 "User-Agent": "profile-readme-gen"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def validate(svg: str, name: str):
    """确保生成的 SVG 是合法 XML —— 语法错误会让整个区块在 GitHub 上消失。"""
    try:
        ET.fromstring(svg)
    except ET.ParseError as e:
        print(f"[FATAL] {name} SVG 非法: {e}", file=sys.stderr)
        sys.exit(1)


def grad_defs(gid: str, colors=None, x2="100%", y2="0%"):
    colors = colors or NEON
    stops = "".join(
        f'<stop offset="{i / (len(colors) - 1) * 100:.0f}%" stop-color="{c}"/>'
        for i, c in enumerate(colors)
    )
    return (
        f'<linearGradient id="{gid}" x1="0%" y1="0%" x2="{x2}" y2="{y2}">{stops}</linearGradient>'
    )


def svg_open(h: int, extra=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" '
        f'viewBox="0 0 {W} {h}" fill="none" style="max-width:100%;height:auto"{extra}>'
    )


def wave_path(y0: int, amp: float, wl: float, phase: float, width: int, h: int,
              steps: int = 160):
    """生成一条从 x=0 到 width 的正弦波浪路径，并闭合到底部。"""
    import math
    pts = []
    for i in range(steps + 1):
        x = width * i / steps
        y = y0 + amp * math.sin(2 * math.pi * (x / wl) + phase)
        pts.append(f"{x:.1f},{y:.1f}")
    return f"M0,{h} L0,{pts[0].split(',')[1]} " + " L".join(pts) + f" L{width},{h} Z"


# ---------------------------------------------------------------- 数据

def fetch_all():
    token = get_token()
    if not token:
        print("[FATAL] 拿不到 GitHub token：请 gh auth login 或设置 GITHUB_TOKEN",
              file=sys.stderr)
        sys.exit(1)

    user = api_get(f"https://api.github.com/users/{USER}", token)
    repos = api_get(
        f"https://api.github.com/users/{USER}/repos?per_page=100&sort=updated", token)
    events = api_get(
        f"https://api.github.com/users/{USER}/events/public?per_page=30", token)

    gql = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }
    """
    g = api_graphql(gql, {"login": USER}, token)
    if "errors" in g:
        print("[FATAL] GraphQL:", g["errors"], file=sys.stderr)
        sys.exit(1)
    cal = g["data"]["user"]["contributionsCollection"]["contributionCalendar"]

    days = []
    for wk in cal["weeks"]:
        for d in wk["contributionDays"]:
            days.append({
                "date": datetime.strptime(d["date"], "%Y-%m-%d").date(),
                "count": d["contributionCount"],
            })
    days.sort(key=lambda x: x["date"])

    return {
        "token": token,
        "user": user,
        "repos": repos,
        "events": events,
        "cal": cal,
        "days": days,
    }


def calc_streaks(days):
    """返回 (最长连续, 当前连续)。今天还没过完，不计入断连判定。"""
    longest = run = 0
    for d in days:
        if d["count"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    today = datetime.now(TZ).date()
    current = 0
    for d in reversed(days):
        if d["count"] > 0:
            current += 1
        elif d["date"] == today:
            continue  # 今天还没结束，不算断
        else:
            break
    return longest, current


# ---------------------------------------------------------------- SVG: 头图

def svg_header():
    h = 210
    g1 = grad_defs("hg", NEON)
    g2 = grad_defs("hg2", ["#7C3AED", "#DB2777", "#0891B2"])
    w1 = wave_path(150, 14, 400, 0, W * 2, h)
    w2 = wave_path(170, 10, 300, 1.6, W * 2, h)
    w3 = wave_path(186, 7, 500, 3.1, W * 2, h)
    return (
        svg_open(h) +
        f"<defs>{g1}{g2}"
        f'<radialGradient id="glow"><stop offset="0%" stop-color="#A855F7" '
        f'stop-opacity="0.35"/><stop offset="100%" stop-color="#A855F7" stop-opacity="0"/>'
        f'</radialGradient></defs>'
        f'<rect x="0" y="0" width="{W}" height="{h}" rx="14" fill="{C_BG}" stroke="{C_BORDER}"/>'
        f'<circle cx="400" cy="80" r="118" fill="url(#glow)"/>'
        # 波浪（平移一个屏宽后与初始状态重合，形成无缝循环）
        f'<g><animateTransform attributeName="transform" type="translate" '
        f'from="0 0" to="-{W} 0" dur="18s" repeatCount="indefinite"/>'
        f'<path d="{w1}" fill="url(#hg2)" opacity="0.30"/>'
        f'<path d="{w2}" fill="url(#hg)" opacity="0.35"/>'
        f'<path d="{w3}" fill="url(#hg)" opacity="0.55"/>'
        f'</g>'
        # 标题
        f'<text x="400" y="104" text-anchor="middle" font-family="{SANS}" '
        f'font-size="42" font-weight="700" fill="url(#hg)">琉璃幻影</text>'
        f'<text x="400" y="132" text-anchor="middle" font-family="{MONO}" '
        f'font-size="13" fill="{C_MUTED}">liu-li-huan-ying</text>'
        f'<text x="400" y="158" text-anchor="middle" font-family="{SANS}" '
        f'font-size="14" fill="{C_TEXT}" opacity="0.85">'
        f'独立开发者 · 造趁手的工具</text>'
        f'<text x="400" y="176" text-anchor="middle" font-family="{MONO}" '
        f'font-size="11" fill="{C_DIM}">Independent builder · Tools that respect your data</text>'
        f"</svg>"
    )


# ---------------------------------------------------------------- SVG: 打字机

def svg_typing():
    h = 62
    lines = [
        ("我写工具，先解决自己的问题，再顺手开源。", SANS, 20, 0.085, 0.0),
        ("Build for myself first, then open-source it.", MONO, 13, 0.028, 1.7),
    ]
    out = [svg_open(h), f"<defs>{grad_defs('tg', NEON)}</defs>"]
    y = 26
    for text, font, size, per_char, delay in lines:
        mono = font == MONO
        cw = size * 0.6 if mono else size  # 中文按全角宽，等宽字体按 0.6em
        total = len(text) * cw
        x0 = (W - total) / 2
        for i, ch in enumerate(text):
            begin = delay + i * per_char
            color = "url(#tg)" if not mono else C_MUTED
            out.append(
                f'<text x="{x0 + i * cw:.1f}" y="{y}" font-family="{font}" font-size="{size}" '
                f'font-weight="600" fill="{color}" opacity="0">'
                f'<animate attributeName="opacity" from="0" to="1" dur="0.01" '
                f'begin="{begin:.2f}s" fill="freeze"/>{esc(ch)}</text>'
            )
        # 光标：随打字逐格右移，随后闪烁
        cursor_x = [f"{x0:.1f}"]
        last = delay
        for i in range(len(text)):
            cursor_x.append(f"{x0 + (i + 1) * cw:.1f}")
        duration = delay + len(text) * per_char
        values = ";".join(cursor_x + [cursor_x[-1]])
        out.append(
            f'<rect x="{x0:.1f}" y="{y - size + 3}" width="{2 if mono else 3}" '
            f'height="{size + 2}" fill="#EC4899">'
            f'<animate attributeName="x" values="{values}" dur="{duration:.2f}s" '
            f'fill="freeze"/>'
            f'<animate attributeName="opacity" values="1;1;0;0" dur="1s" '
            f'begin="{duration:.2f}s" repeatCount="indefinite"/></rect>'
        )
        y += 30
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- SVG: 数据卡

def svg_stats(d, stats):
    cols, rows = 3, 2
    gap = 14
    cw = (W - gap * (cols - 1)) // cols
    ch = 78
    h = rows * ch + gap * (rows - 1) + 8
    items = [
        ("✨", "总贡献", "Contributions", f"{stats['total']:,}"),
        ("⭐", "获得 Star", "Stars earned", str(stats["stars"])),
        ("📦", "公开仓库", "Public repos", str(stats["repos"])),
        ("👥", "关注者", "Followers", str(stats["followers"])),
        ("🔥", "最长连续", "Longest streak", f"{stats['longest']} 天"),
        ("⚡", "当前连续", "Current streak", f"{stats['current']} 天"),
    ]
    out = [svg_open(h), f"<defs>{grad_defs('sg', NEON)}"]
    for i in range(len(items)):
        x = (i % cols) * (cw + gap)
        y = (i // cols) * (ch + gap) + 4
        out.append(
            f'<clipPath id="c{i}"><rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="12"/>'
            f'</clipPath>'
        )
    out.append("</defs>")
    for i, (icon, zh, en, val) in enumerate(items):
        x = (i % cols) * (cw + gap)
        y = (i // cols) * (ch + gap) + 4
        out.append(
            f'<g clip-path="url(#c{i})">'
            f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" fill="{C_CARD}"/>'
            f'<rect x="{x}" y="{y}" width="{cw}" height="3" fill="url(#sg)"/>'
            f'</g>'
            f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="12" '
            f'fill="none" stroke="{C_BORDER}"/>'
        )
        cx = x + cw / 2
        out.append(
            f'<text x="{cx}" y="{y + 30}" text-anchor="middle" font-family="{SANS}" '
            f'font-size="13" fill="{C_MUTED}">{icon} {esc(zh)}</text>'
            f'<text x="{cx}" y="{y + 58}" text-anchor="middle" font-family="{MONO}" '
            f'font-size="25" font-weight="700" fill="url(#sg)">{esc(val)}</text>'
            f'<text x="{cx}" y="{y + 72}" text-anchor="middle" font-family="{MONO}" '
            f'font-size="9" fill="{C_DIM}">{esc(en)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- SVG: 热力图

LEVELS = ["#161B22", "#2C1250", "#6D28D9", "#A855F7", "#F472B6"]


def svg_graph(d):
    days = d["days"]
    cell, gap = 11.5, 2.5
    left, top = 34, 26
    cols = len(days) // 7
    h = top + 7 * (cell + gap) + 34
    out = [svg_open(h), f"<defs>{grad_defs('gg', NEON)}</defs>"]

    # 星期标签（周一 / 周三 / 周五）
    for idx, label in ((1, "一"), (3, "三"), (5, "五")):
        out.append(
            f'<text x="26" y="{top + idx * (cell + gap) + cell - 2}" text-anchor="end" '
            f'font-family="{SANS}" font-size="10" fill="{C_DIM}">{label}</text>'
        )

    # 月份标签
    last_m = None
    for w_i in range(cols):
        day = days[w_i * 7]
        if day["date"].month != last_m:
            last_m = day["date"].month
            out.append(
                f'<text x="{left + w_i * (cell + gap):.1f}" y="{top - 8}" '
                f'font-family="{MONO}" font-size="10" fill="{C_DIM}">{last_m}</text>'
            )

    def level(c):
        if c == 0:
            return 0
        if c <= 3:
            return 1
        if c <= 7:
            return 2
        if c <= 14:
            return 3
        return 4

    for i, day in enumerate(days):
        w_i, d_i = divmod(i, 7)
        x = left + w_i * (cell + gap)
        y = top + d_i * (cell + gap)
        lv = level(day["count"])
        fill = LEVELS[lv]
        stroke = C_BORDER if lv == 0 else "none"
        tip = f"{day['date'].isoformat()} · {day['count']} 次贡献"
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" rx="3" '
            f'fill="{fill}" stroke="{stroke}"><title>{esc(tip)}</title></rect>'
        )

    total = d["cal"]["totalContributions"]
    longest, current = calc_streaks(days)
    out.append(
        f'<text x="{left}" y="{h - 12}" font-family="{SANS}" font-size="12" fill="{C_MUTED}">'
        f'近一年 {total:,} 次贡献 · 最长连续 {longest} 天 · 当前连续 {current} 天</text>'
    )
    # 图例
    lx = W - 8 - (5 * (cell + 4)) - 60
    out.append(
        f'<text x="{lx - 8}" y="{h - 12}" text-anchor="end" font-family="{SANS}" '
        f'font-size="11" fill="{C_DIM}">少</text>'
    )
    for i, c in enumerate(LEVELS):
        out.append(
            f'<rect x="{lx + i * (cell + 4):.1f}" y="{h - 22}" width="{cell}" '
            f'height="{cell}" rx="3" fill="{c}" stroke="{C_BORDER if i == 0 else "none"}"/>'
        )
    out.append(
        f'<text x="{lx + 5 * (cell + 4) + 4:.1f}" y="{h - 12}" font-family="{SANS}" '
        f'font-size="11" fill="{C_DIM}">多</text>'
    )
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- SVG: 语言分布

def svg_langs(d):
    repos = [r for r in d["repos"] if not r.get("fork")]
    agg = {}
    for r in repos:
        lang = r.get("language")
        if not lang:
            continue
        agg[lang] = agg.get(lang, 0) + (r.get("size") or 0)
    if not agg:
        return ""
    total = sum(agg.values())
    items = sorted(agg.items(), key=lambda kv: -kv[1])
    top = items[:8]

    bar_h, h = 16, 118
    out = [svg_open(h)]
    out.append(f'<rect x="0" y="0" width="{W}" height="{bar_h}" rx="8" fill="{C_CARD}"/>')
    x = 0.0
    segs = []
    for lang, size in top:
        w = W * size / total
        segs.append((x, w, LANG_COLORS.get(lang, FALLBACK_COLOR), lang))
        x += w
    out.append(
        f'<clipPath id="lbar"><rect x="0" y="0" width="{W}" height="{bar_h}" rx="8"/></clipPath>'
        f'<g clip-path="url(#lbar)">'
    )
    for i, (sx, sw, color, lang) in enumerate(segs):
        # 段间多铺 0.6px 消除缝隙，最后一段不加，避免整体越出画布
        sw = sw if i == len(segs) - 1 else sw + 0.6
        out.append(
            f'<rect x="{sx:.1f}" y="0" width="{sw:.1f}" height="{bar_h}" fill="{color}">'
            f'<title>{esc(lang)}</title></rect>'
        )
    out.append("</g>")

    # 图例：两行
    per_row = 4
    for i, (lang, size) in enumerate(top):
        row, col = divmod(i, per_row)
        lx = col * (W / per_row)
        ly = 44 + row * 30
        pct = size / total * 100
        color = LANG_COLORS.get(lang, FALLBACK_COLOR)
        out.append(
            f'<circle cx="{lx + 8}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 20}" y="{ly}" font-family="{SANS}" font-size="13" '
            f'fill="{C_TEXT}">{esc(lang)}</text>'
            f'<text x="{lx + 20}" y="{ly + 14}" font-family="{MONO}" font-size="10" '
            f'fill="{C_DIM}">{pct:.1f}%</text>'
        )
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- SVG: 动态

def event_text(e):
    t = e["type"]
    repo = e["repo"]["name"].split("/")[-1]
    p = e.get("payload") or {}
    if t == "PushEvent":
        n = len(p.get("commits") or [])
        return f"推送 {n} 次提交到 <b>{repo}</b>" if n else f"推送提交到 <b>{repo}</b>"
    if t == "CreateEvent":
        rt = p.get("ref_type")
        return {
            "repository": f"创建了仓库 <b>{repo}</b>",
            "branch": f"在 <b>{repo}</b> 新建分支 {p.get('ref', '')}",
            "tag": f"在 <b>{repo}</b> 打标签 {p.get('ref', '')}",
        }.get(rt, f"在 <b>{repo}</b> 创建了 {rt}")
    if t == "WatchEvent":
        return f"给 <b>{repo}</b> 点了 Star"
    if t == "ForkEvent":
        return f"派生了 <b>{repo}</b>"
    if t == "IssuesEvent":
        act = {"opened": "提出", "closed": "关闭", "reopened": "重开"}.get(
            p.get("action"), p.get("action"))
        return f"{act}议题 · <b>{repo}</b>"
    if t == "PullRequestEvent":
        act = p.get("action")
        pr = (p.get("pull_request") or {})
        if act == "closed" and pr.get("merged"):
            return f"合并了 PR · <b>{repo}</b>"
        return {"opened": "发起 PR", "closed": "关闭 PR"}.get(act, "PR") + f" · <b>{repo}</b>"
    if t == "DeleteEvent":
        return f"删除了 <b>{repo}</b> 的 {p.get('ref_type', '')}"
    if t == "ReleaseEvent":
        return f"发布 <b>{repo}</b> 新版本"
    if t == "IssueCommentEvent":
        return f"在 <b>{repo}</b> 评论了议题"
    if t == "PublicEvent":
        return f"把 <b>{repo}</b> 转为公开"
    if t == "MemberEvent":
        return f"加入 <b>{repo}</b>"
    if t == "CommitCommentEvent":
        return f"在 <b>{repo}</b> 评论了提交"
    if t == "GollumEvent":
        return f"编辑了 <b>{repo}</b> 的 Wiki"
    return f"{t} · <b>{repo}</b>"


def svg_feed(d, limit=7):
    events = d["events"][:limit]
    if not events:
        return ""
    row_h = 32
    h = len(events) * row_h + 10
    now = datetime.now(TZ)
    out = [svg_open(h), f"<defs>{grad_defs('fg', NEON)}</defs>"]
    for i, e in enumerate(events):
        y = 16 + i * row_h
        t = datetime.strptime(e["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).astimezone(TZ)
        delta = now - t
        if delta.days == 0:
            ago = "今天"
        elif delta.days == 1:
            ago = "昨天"
        elif delta.days < 30:
            ago = f"{delta.days} 天前"
        else:
            ago = f"{delta.days // 30} 个月前"

        out.append(
            f'<circle cx="12" cy="{y - 4}" r="4" fill="url(#fg)"/>'
            f'<circle cx="12" cy="{y - 4}" r="8" fill="none" stroke="#A855F7" '
            f'stroke-opacity="0.25"/>'
        )
        text = event_text(e)
        # 加粗仓库名：<b> → 单独 text 片段（SVG 内用 tspan 更简单，这里直接拼整行）
        plain = text.replace("<b>", "").replace("</b>", "")
        out.append(
            f'<text x="30" y="{y}" font-family="{SANS}" font-size="13.5" fill="{C_TEXT}">'
            f'{esc(plain)}</text>'
        )
        out.append(
            f'<text x="{W}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="11" '
            f'fill="{C_DIM}">{esc(ago)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- SVG: 技能 chips

def svg_skills():
    pad, h_gap, v_gap, ch_h = 10, 10, 10, 30
    # 粗略按字宽估算每个 chip 宽度后贪心换行
    def cw(s):
        return len(s) * 8.6 + pad * 2

    def row_width(row):
        return sum(cw(s) for s in row) + h_gap * (len(row) - 1)

    rows, cur = [], []
    for s in SKILLS:
        trial = cur + [s]
        if cur and row_width(trial) > W:
            rows.append(cur)
            cur = [s]
        else:
            cur = trial
    if cur:
        rows.append(cur)

    h = len(rows) * (ch_h + v_gap)
    out = [svg_open(h), f"<defs>{grad_defs('kg', NEON)}</defs>"]
    colors = ["#A855F7", "#EC4899", "#06B6D4", "#8B5CF6"]
    for r_i, row in enumerate(rows):
        total_w = sum(cw(s) for s in row) + h_gap * (len(row) - 1)
        x = (W - total_w) / 2
        y = r_i * (ch_h + v_gap)
        for i, s in enumerate(row):
            w = cw(s)
            c = colors[(r_i * len(row) + i) % len(colors)]
            out.append(
                f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{ch_h}" rx="15" '
                f'fill="{c}" fill-opacity="0.08" stroke="{c}" stroke-opacity="0.55"/>'
                f'<text x="{x + w / 2:.1f}" y="{y + 20}" text-anchor="middle" '
                f'font-family="{SANS}" font-size="13" fill="{C_TEXT}">{esc(s)}</text>'
            )
            x += w + h_gap
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- SVG: 徽章

def svg_badges(d):
    longest, current = calc_streaks(d["days"])
    items = [
        (f"🔥 连续提交 {current} 天", "#A855F7"),
        (f"🛠 {len([r for r in d['repos'] if not r.get('fork')])} 个原创仓库", "#EC4899"),
        ("🌏 China · UTC+8", "#06B6D4"),
        (f"📅 GitHub 自 2018", "#8B5CF6"),
    ]
    h_gap, h = 10, 30
    widths = [len(s) * 9 + 26 for s, _ in items]
    total = sum(widths) + h_gap * (len(items) - 1)
    if total > W:  # 窄屏保护：等分缩放
        scale = W / total
        widths = [w * scale for w in widths]
        total = W
    out = [svg_open(h)]
    x = (W - total) / 2
    for (text, color), w in zip(items, widths):
        out.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{h}" rx="8" '
            f'fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-opacity="0.6"/>'
            f'<text x="{x + w / 2:.1f}" y="20" text-anchor="middle" font-family="{SANS}" '
            f'font-size="12.5" fill="{C_TEXT}">{esc(text)}</text>'
        )
        x += w + h_gap
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- SVG: 页脚波浪

def svg_footer():
    h = 70
    g = grad_defs("fog", ["#06B6D4", "#A855F7", "#EC4899"])
    w1 = wave_path(34, 8, 380, 0.4, W * 2, h)
    w2 = wave_path(46, 6, 260, 2.2, W * 2, h)
    return (
        svg_open(h, ' role="presentation"') +
        f"<defs>{g}</defs>"
        f'<g><animateTransform attributeName="transform" type="translate" '
        f'from="0 0" to="-{W} 0" dur="22s" repeatCount="indefinite"/>'
        f'<path d="{w1}" fill="url(#fog)" opacity="0.35"/>'
        f'<path d="{w2}" fill="url(#fog)" opacity="0.6"/></g>'
        f"</svg>"
    )


# ---------------------------------------------------------------- 主流程

def main():
    d = fetch_all()
    longest, current = calc_streaks(d["days"])
    own_repos = [r for r in d["repos"] if not r.get("fork")]
    stats = {
        "total": d["cal"]["totalContributions"],
        "stars": sum(r["stargazers_count"] for r in d["repos"]),
        "repos": len(d["repos"]),
        "followers": d["user"]["followers"],
        "longest": longest,
        "current": current,
    }

    parts = {
        "HEADER": svg_header(),
        "TYPING": svg_typing(),
        "BADGES": svg_badges(d),
        "STATS": svg_stats(d, stats),
        "GRAPH": svg_graph(d),
        "LANGS": svg_langs(d),
        "FEED": svg_feed(d),
        "SKILLS": svg_skills(),
        "FOOTER": svg_footer(),
        "UPDATED": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
    }
    for k, v in parts.items():
        if v.startswith("<svg"):
            validate(v, k)

    tpl_path = os.path.join(ROOT, "template.md")
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()
    for k, v in parts.items():
        tpl = tpl.replace(f"<!--{k}-->", v)

    out_md = os.path.join(ROOT, "README.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(tpl)

    # 本地预览页
    prev = ["<!doctype html><meta charset='utf-8'><title>主页预览</title>",
            "<body style='margin:0;background:#010409;display:flex;flex-direction:column;"
            "align-items:center;gap:18px;padding:28px 16px'>",
            "<div style='width:800px;max-width:100%;display:flex;flex-direction:column;"
            "gap:18px'>"]
    for k in ["HEADER", "TYPING", "BADGES", "STATS", "GRAPH", "LANGS", "SKILLS", "FEED",
              "FOOTER"]:
        prev.append(f"<div><!-- {k} -->{parts[k]}</div>")
    prev.append("</div></body>")
    with open(os.path.join(ROOT, "preview.html"), "w", encoding="utf-8") as f:
        f.write("".join(prev))

    print(f"README.md 已生成 | 贡献 {stats['total']} · Star {stats['stars']} · "
          f"最长连续 {longest} 天 · 当前连续 {current} 天")


if __name__ == "__main__":
    main()
