#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GitHub 主页 README —— 自制 SVG 卡片（零外部依赖），editorial 暗色风格。

设计语言：墨黑底 + 哑光金单一强调色 + 衬线标题 + 细线分隔。克制、留白、对齐。
所有卡片输出为 assets/*.svg 文件，README 用 <img src="assets/xxx.svg"> 引用
（GitHub README 不允许内联 <svg>，必须走图片引用）。

用法: python scripts/generate.py   （需 gh 已登录或设置 GITHUB_TOKEN）
输出: README.md / assets/*.svg / preview.html
"""

import base64
import json
import os
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

USER = "liu-li-huan-ying"
W = 720  # 容器宽度

# —— 配色：墨黑 / 暖白 / 冷灰 / 哑光金（单一克制强调色）——
C_BG = "#0b0e14"
C_SURFACE = "#0e1219"
C_HAIR = "#222833"
C_TEXT = "#ECEAE4"
C_DIM = "#878d97"
C_MUTE = "#565c66"
C_GOLD = "#C8A97E"
C_GOLD_SOFT = "#E6D2B0"

SERIF = "'Georgia','Noto Serif SC','Songti SC',serif"
SANS = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
    "'Hiragino Sans GB','Microsoft YaHei',sans-serif"
)
MONO = "'SFMono-Regular',Consolas,'Cascadia Code','Liberation Mono',monospace"

LANG_COLORS = {
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Vue": "#41b883",
    "Go": "#00ADD8", "C++": "#f34b7d", "Rust": "#dea584", "Python": "#3572A5",
    "HTML": "#e34c26", "CSS": "#563d7c", "Java": "#b07219", "C": "#555555",
    "Shell": "#89e051", "Ruby": "#701516", "PHP": "#4F5D95", "Swift": "#F05138",
    "Kotlin": "#A97BFF", "Dart": "#00B4AB", "Lua": "#000080", "Makefile": "#427819",
    "CMake": "#DA3434", "C#": "#178600", "SCSS": "#c6538c",
}
FALLBACK = "#5a606b"

SKILLS = [
    "JavaScript", "TypeScript", "Vue 3", "React Native", "Node.js",
    "Go", "C++", "Rust", "HTML / CSS", "Git",
    "Docker", "Linux", "Chrome 扩展", "Obsidian 插件",
]

TZ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


# ---------------------------------------------------------------- 工具

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("PAT")
    if tok:
        return tok.strip()
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def api_get(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": "token " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-readme-gen",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def api_graphql(query, variables, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": "token " + token, "Content-Type": "application/json",
                 "User-Agent": "profile-readme-gen"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def validate(svg, name):
    try:
        ET.fromstring(svg)
    except ET.ParseError as e:
        print(f"[FATAL] {name} SVG 非法: {e}", file=sys.stderr)
        sys.exit(1)


def grad_defs(gid, colors):
    stops = "".join(
        f'<stop offset="{i / (len(colors) - 1) * 100:.0f}%" stop-color="{c}"/>'
        for i, c in enumerate(colors))
    return (f'<linearGradient id="{gid}" x1="0%" y1="0%" x2="100%" y2="0%">'
            f'{stops}</linearGradient>')


def svg_open(h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" '
            f'viewBox="0 0 {W} {h}" fill="none" '
            f'style="max-width:100%;height:auto">')


def card(h, inner):
    return (svg_open(h)
            + f"<defs>{grad_defs('gold',[C_GOLD,C_GOLD_SOFT])}</defs>"
            + f'<rect x="0" y="0" width="{W}" height="{h}" rx="6" '
            f'fill="{C_BG}" stroke="{C_HAIR}" stroke-width="1"/>'
            + inner + "</svg>")


def data_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# ---------------------------------------------------------------- 数据

def fetch_all():
    token = get_token()
    if not token:
        print("[FATAL] 拿不到 GitHub token：请 gh auth login 或设置 GITHUB_TOKEN",
              file=sys.stderr)
        sys.exit(1)

    user = api_get(f"https://api.github.com/users/{USER}", token)
    repos = api_get(f"https://api.github.com/users/{USER}/repos?per_page=100&sort=updated", token)
    events = api_get(f"https://api.github.com/users/{USER}/events/public?per_page=30", token)

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
            days.append({"date": datetime.strptime(d["date"], "%Y-%m-%d").date(),
                         "count": d["contributionCount"]})
    days.sort(key=lambda x: x["date"])
    return {"user": user, "repos": repos, "events": events, "cal": cal, "days": days}


def calc_streaks(days):
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
            continue
        else:
            break
    return longest, current


# ---------------------------------------------------------------- SVG 模块

def svg_header():
    h = 200
    inner = (
        f'<rect x="{(W-56)/2:.0f}" y="56" width="56" height="2" fill="url(#gold)"/>'
        f'<text x="{W/2}" y="106" text-anchor="middle" font-family="{SERIF}" '
        f'font-size="40" fill="{C_TEXT}">琉璃幻影</text>'
        f'<text x="{W/2}" y="130" text-anchor="middle" font-family="{MONO}" '
        f'font-size="11" letter-spacing="4" fill="{C_GOLD}">INDEPENDENT BUILDER</text>'
        f'<text x="{W/2}" y="154" text-anchor="middle" font-family="{SANS}" '
        f'font-size="13" fill="{C_DIM}">独立开发者 · 造趁手的工具</text>'
        f'<text x="{W/2}" y="176" text-anchor="middle" font-family="{MONO}" '
        f'font-size="11" letter-spacing="1" fill="{C_MUTE}">'
        f'China · UTC+8 · GitHub since 2018</text>'
        f'<rect x="24" y="192" width="{W-48}" height="1" fill="{C_HAIR}" opacity="0.6"/>'
    )
    return card(h, inner)


def svg_manifesto():
    h = 104
    inner = (
        f'<rect x="{W/2-20:.0f}" y="22" width="40" height="1" fill="{C_GOLD}" opacity="0.7"/>'
        f'<text x="{W/2}" y="56" text-anchor="middle" font-family="{SERIF}" '
        f'font-size="20" fill="{C_TEXT}">我造工具，先为自己，也为同样挑剔的人。</text>'
        f'<text x="{W/2}" y="82" text-anchor="middle" font-family="{SANS}" '
        f'font-size="12.5" font-style="italic" fill="{C_MUTE}">'
        f'Tools I build for myself first — then for people just as picky.</text>'
        f'<rect x="{W/2-20:.0f}" y="96" width="40" height="1" fill="{C_GOLD}" opacity="0.7"/>'
    )
    return card(h, inner)


def svg_stats(stats):
    cols = 4
    colw = W / cols
    h = 124
    inner = []
    for i in range(1, cols):
        inner.append(f'<rect x="{i*colw:.0f}" y="34" width="1" height="58" fill="{C_HAIR}"/>')
    items = [
        ("总贡献", f"{stats['total']:,}"),
        ("公开仓库", str(stats["repos"])),
        ("最长连续", f"{stats['longest']} 天"),
        ("当前连续", f"{stats['current']} 天"),
    ]
    for i, (label, val) in enumerate(items):
        cx = (i + 0.5) * colw
        inner.append(
            f'<text x="{cx:.0f}" y="74" text-anchor="middle" font-family="{SANS}" '
            f'font-size="34" font-weight="200" fill="{C_TEXT}">{esc(val)}</text>'
            f'<text x="{cx:.0f}" y="98" text-anchor="middle" font-family="{MONO}" '
            f'font-size="10" letter-spacing="2" fill="{C_DIM}">{esc(label)}</text>'
        )
    return card(h, "".join(inner))


def svg_graph(d):
    days = d["days"]
    cell, gap = 9, 3
    left, top = 34, 30
    cols = len(days) // 7
    h = top + 7 * (cell + gap) + 34
    LEVELS = ["#161922", "#2a2f1a", "#4a3f22", "#8a7550", C_GOLD]
    out = []

    for idx, label in ((1, "一"), (3, "三"), (5, "五")):
        out.append(
            f'<text x="26" y="{top + idx*(cell+gap) + cell - 2:.0f}" text-anchor="end" '
            f'font-family="{SANS}" font-size="9" fill="{C_MUTE}">{label}</text>')
    last_m = None
    for w_i in range(cols):
        day = days[w_i * 7]
        if day["date"].month != last_m:
            last_m = day["date"].month
            out.append(
                f'<text x="{left + w_i*(cell+gap):.0f}" y="{top - 10}" '
                f'font-family="{MONO}" font-size="9" fill="{C_MUTE}">{last_m}</text>')

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
        stroke = C_HAIR if lv == 0 else "none"
        tip = f"{day['date'].isoformat()} · {day['count']} 次贡献"
        out.append(
            f'<circle cx="{x + cell/2:.1f}" cy="{y + cell/2:.1f}" r="{cell/2:.1f}" '
            f'fill="{fill}" stroke="{stroke}"><title>{esc(tip)}</title></circle>')

    total = d["cal"]["totalContributions"]
    longest, current = calc_streaks(days)
    out.append(
        f'<text x="{left}" y="{h - 12}" font-family="{SANS}" font-size="12" '
        f'fill="{C_DIM}">近一年 <tspan fill="{C_GOLD}">{total:,}</tspan> 次贡献 · '
        f'最长连续 {longest} 天 · 当前连续 {current} 天</text>')
    out.append(
        f'<text x="{W-24}" y="{h - 12}" text-anchor="end" font-family="{SANS}" '
        f'font-size="11" fill="{C_MUTE}">少 · 多</text>')
    return card(h, "".join(out))


def svg_langs(d):
    repos = [r for r in d["repos"] if not r.get("fork")]
    agg = {}
    for r in repos:
        lang = r.get("language")
        if lang:
            agg[lang] = agg.get(lang, 0) + (r.get("size") or 0)
    if not agg:
        return ""
    total = sum(agg.values())
    top = sorted(agg.items(), key=lambda kv: -kv[1])[:8]
    bar_h, h = 5, 120
    out = [f'<rect x="0" y="0" width="{W}" height="{bar_h}" rx="2.5" fill="{C_HAIR}"/>']
    x = 0.0
    for lang, size in top:
        w = W * size / total
        c = LANG_COLORS.get(lang, FALLBACK)
        out.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{bar_h}" rx="2.5" '
            f'fill="{c}"><title>{esc(lang)}</title></rect>')
        x += w
    per_row = 4
    for i, (lang, size) in enumerate(top):
        row, col = divmod(i, per_row)
        lx = col * (W / per_row)
        ly = 40 + row * 32
        pct = size / total * 100
        c = LANG_COLORS.get(lang, FALLBACK)
        out.append(
            f'<circle cx="{lx + 6}" cy="{ly - 4}" r="4.5" fill="{c}"/>'
            f'<text x="{lx + 18}" y="{ly}" font-family="{SANS}" font-size="13" '
            f'fill="{C_TEXT}">{esc(lang)}</text>'
            f'<text x="{lx + 18}" y="{ly + 15}" font-family="{MONO}" font-size="10" '
            f'fill="{C_MUTE}">{pct:.1f}%</text>')
    return card(h, "".join(out))


def svg_skills():
    pad, h_gap, v_gap, ch_h = 14, 10, 12, 30

    def cw(s):
        return len(s) * 7.6 + pad * 2

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
    out = []
    for r_i, row in enumerate(rows):
        total_w = row_width(row)
        x = (W - total_w) / 2
        y = r_i * (ch_h + v_gap)
        for s in row:
            w = cw(s)
            out.append(
                f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{ch_h}" rx="15" '
                f'fill="{C_SURFACE}" stroke="{C_HAIR}"/>'
                f'<text x="{x + w/2:.1f}" y="{y + 20}" text-anchor="middle" '
                f'font-family="{SANS}" font-size="12.5" fill="{C_TEXT}">{esc(s)}</text>')
            x += w + h_gap
    return card(h, "".join(out))


def event_text(e):
    t = e["type"]
    repo = e["repo"]["name"].split("/")[-1]
    p = e.get("payload") or {}
    if t == "PushEvent":
        n = len(p.get("commits") or [])
        return f"推送 {n} 次提交到 {repo}" if n else f"推送提交到 {repo}"
    if t == "CreateEvent":
        rt = p.get("ref_type")
        return {"repository": f"创建了仓库 {repo}",
                "branch": f"在 {repo} 新建分支 {p.get('ref', '')}",
                "tag": f"在 {repo} 打标签 {p.get('ref', '')}"}.get(rt, f"在 {repo} 创建 {rt}")
    if t == "WatchEvent":
        return f"给 {repo} 加了 Star"
    if t == "ForkEvent":
        return f"派生了 {repo}"
    if t == "IssuesEvent":
        act = {"opened": "提出", "closed": "关闭", "reopened": "重开"}.get(p.get("action"), p.get("action"))
        return f"{act}议题 · {repo}"
    if t == "PullRequestEvent":
        act = p.get("action")
        pr = p.get("pull_request") or {}
        if act == "closed" and pr.get("merged"):
            return f"合并了 PR · {repo}"
        return {"opened": "发起 PR", "closed": "关闭 PR"}.get(act, "PR") + f" · {repo}"
    if t == "DeleteEvent":
        return f"删除了 {repo} 的 {p.get('ref_type', '')}"
    if t == "ReleaseEvent":
        return f"发布 {repo} 新版本"
    if t == "IssueCommentEvent":
        return f"在 {repo} 评论了议题"
    if t == "PublicEvent":
        return f"把 {repo} 转为公开"
    if t == "MemberEvent":
        return f"加入 {repo}"
    if t == "CommitCommentEvent":
        return f"在 {repo} 评论了提交"
    if t == "GollumEvent":
        return f"编辑了 {repo} 的 Wiki"
    return f"{t} · {repo}"


def svg_feed(d, limit=7):
    events = d["events"][:limit]
    if not events:
        return ""
    row_h = 30
    h = len(events) * row_h + 10
    now = datetime.now(TZ)
    out = []
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
            f'<circle cx="10" cy="{y - 4}" r="3" fill="{C_GOLD}"/>'
            f'<text x="26" y="{y}" font-family="{SANS}" font-size="13" fill="{C_TEXT}">'
            f'{esc(event_text(e))}</text>'
            f'<text x="{W}" y="{y}" text-anchor="end" font-family="{MONO}" '
            f'font-size="11" fill="{C_MUTE}">{esc(ago)}</text>')
        if i < len(events) - 1:
            out.append(f'<rect x="10" y="{y + 9}" width="1" height="11" fill="{C_HAIR}"/>')
    return card(h, "".join(out))


def svg_footer():
    h = 46
    inner = (
        f'<rect x="120" y="14" width="{W-240}" height="1" fill="{C_HAIR}" opacity="0.7"/>'
        f'<text x="{W/2}" y="32" text-anchor="middle" font-family="{MONO}" '
        f'font-size="11" letter-spacing="1" fill="{C_MUTE}">Crafted with restraint · 2026</text>'
    )
    return card(h, inner)


# ---------------------------------------------------------------- 主流程

def main():
    d = fetch_all()
    longest, current = calc_streaks(d["days"])
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
        "MANIFESTO": svg_manifesto(),
        "STATS": svg_stats(stats),
        "GRAPH": svg_graph(d),
        "LANGS": svg_langs(d),
        "SKILLS": svg_skills(),
        "FEED": svg_feed(d),
        "FOOTER": svg_footer(),
        "UPDATED": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
    }
    os.makedirs(ASSETS, exist_ok=True)
    for k, v in parts.items():
        if v.startswith("<svg"):
            validate(v, k)
            with open(os.path.join(ASSETS, f"{k.lower()}.svg"), "w", encoding="utf-8") as f:
                f.write(v)

    tpl_path = os.path.join(ROOT, "template.md")
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()
    for k, v in parts.items():
        alt = {"HEADER": "琉璃幻影", "MANIFESTO": "个人宣言", "STATS": "GitHub 数据",
               "GRAPH": "贡献热力图", "LANGS": "语言分布", "SKILLS": "技术栈",
               "FEED": "最近动态", "FOOTER": "页脚", "UPDATED": "更新时间"}[k]
        if k == "UPDATED":
            tpl = tpl.replace(f"<!--{k}-->", v)
        else:
            tpl = tpl.replace(f"<!--{k}-->",
                              f'<img src="assets/{k.lower()}.svg" alt="{alt}" />')

    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8") as f:
        f.write(tpl)

    prev = ["<!doctype html><meta charset='utf-8'><title>主页预览</title>",
            "<body style='margin:0;background:#010409;display:flex;flex-direction:column;"
            "align-items:center;gap:16px;padding:28px 16px'>",
            "<div style='width:720px;max-width:100%;display:flex;flex-direction:column;"
            "gap:16px'>"]
    for k in ["HEADER", "MANIFESTO", "STATS", "GRAPH", "LANGS", "SKILLS", "FEED", "FOOTER"]:
        prev.append(f"<div style='border-radius:8px;overflow:hidden'>"
                    f"<img src='{data_uri(parts[k])}' style='width:100%;display:block'/></div>")
    prev.append("</div></body>")
    with open(os.path.join(ROOT, "preview.html"), "w", encoding="utf-8") as f:
        f.write("".join(prev))

    print(f"README 已生成 | 贡献 {stats['total']} · 仓库 {stats['repos']} · "
          f"最长连续 {longest} 天 · 当前连续 {current} 天")


if __name__ == "__main__":
    main()
