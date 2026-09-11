#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GitHub 主页 README —— 自制 SVG 片段（零外部依赖），融入式 editorial 风格。

设计语言：墨黑+哑光金单一强调色 + 衬线标题 + 细线分隔，克制、留白、对齐。
关键改造（融入式）：
  - 所有 SVG 透明底、无背景、无边框、无圆角外壳 —— 直接画在 GitHub 容器上，
    避免「框中框」不伦不类。
  - 内置 prefers-color-scheme 明暗双配色（CSS 变量 + @media），亮色 GitHub 也不会白底黑字瞎眼。
  - 贡献图不重复画原生热力图，改画「近 12 个月贡献柱状图」与原生互补。
所有片段输出为 assets/*.svg，README 用 <img src="assets/xxx.svg"> 引用
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
from collections import defaultdict
from datetime import datetime, timedelta, timezone

USER = "liu-li-huan-ying"
W = 720  # 容器宽度

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

# —— 双配色：CSS 变量 + 媒体查询。透明底，文字/描边随 GitHub 明暗自适应 ——
# 默认（暗色 GitHub）用亮字；亮色 GitHub（prefers-color-scheme: light）翻成深字。
STYLE = (
    "<style>"
    ":root{--text:#ECEAE4;--dim:#8b919b;--mute:#6b7280;--gold:#C8A97E;"
    "--soft:#E6D2B0;--goldhi:#D9BB8C;--hair:#232a35}"
    "@media (prefers-color-scheme: light){"
    ":root{--text:#1f2328;--dim:#59636e;--mute:#818b96;--gold:#9a753f;"
    "--soft:#7d5e30;--goldhi:#b8945a;--hair:#d1d9e0}}"
    ".t{fill:var(--text)}.d{fill:var(--dim)}.m{fill:var(--mute)}"
    ".g{fill:var(--gold)}.s{fill:var(--soft)}.h{fill:var(--hair)}"
    ".hb{fill:none;stroke:var(--hair);stroke-width:1}"
    ".gs{fill:var(--gold);opacity:.72}.gd{fill:var(--gold);opacity:.45}"
    ".hf{fill:var(--hair);opacity:.16}"
    "</style>"
)


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


def svg_open(h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" '
            f'viewBox="0 0 {W} {h}" fill="none" '
            f'style="max-width:100%;height:auto">')


def panel(h, inner):
    """透明底、无外壳的 SVG 片段。"""
    defs = ('<defs><linearGradient id="barg" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="var(--goldhi)"/>'
            '<stop offset="1" stop-color="var(--gold)"/></linearGradient></defs>')
    return svg_open(h) + defs + STYLE + inner + "</svg>"


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
    h = 196
    inner = (
        f'<rect x="{(W-56)/2:.0f}" y="56" width="56" height="2" class="g"/>'
        f'<text x="{W/2}" y="106" text-anchor="middle" font-family="{SERIF}" '
        f'font-size="40" class="t">琉璃幻影</text>'
        f'<text x="{W/2}" y="130" text-anchor="middle" font-family="{MONO}" '
        f'font-size="11" letter-spacing="4" class="g">INDEPENDENT BUILDER</text>'
        f'<text x="{W/2}" y="154" text-anchor="middle" font-family="{SANS}" '
        f'font-size="13" class="d">独立开发者 · 造趁手的工具</text>'
        f'<text x="{W/2}" y="176" text-anchor="middle" font-family="{MONO}" '
        f'font-size="11" letter-spacing="1" class="m">China · UTC+8 · GitHub since 2018</text>'
        f'<rect x="24" y="188" width="{W-48}" height="1" class="h"/>'
    )
    return panel(h, inner)


def svg_manifesto():
    h = 104
    inner = (
        f'<rect x="{W/2-20:.0f}" y="22" width="40" height="1" class="g"/>'
        f'<text x="{W/2}" y="56" text-anchor="middle" font-family="{SERIF}" '
        f'font-size="20" class="t">我造工具，先为自己，也为同样挑剔的人。</text>'
        f'<text x="{W/2}" y="82" text-anchor="middle" font-family="{SANS}" '
        f'font-size="12.5" font-style="italic" class="m">'
        f'Tools I build for myself first — then for people just as picky.</text>'
        f'<rect x="{W/2-20:.0f}" y="96" width="40" height="1" class="g"/>'
    )
    return panel(h, inner)


def svg_stats(stats):
    cols = 4
    colw = W / cols
    h = 120
    inner = []
    for i in range(1, cols):
        inner.append(f'<rect x="{i*colw:.0f}" y="34" width="1" height="58" class="h"/>')
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
            f'font-size="34" font-weight="200" class="t">{esc(val)}</text>'
            f'<text x="{cx:.0f}" y="98" text-anchor="middle" font-family="{MONO}" '
            f'font-size="10" letter-spacing="2" class="d">{esc(label)}</text>'
        )
    return panel(h, "".join(inner))


def svg_monthly(d):
    """近 12 个月贡献柱状图 —— 与原生热力图互补，不重复。"""
    md = defaultdict(int)
    for day in d["days"]:
        md[(day["date"].year, day["date"].month)] += day["count"]
    today = datetime.now(TZ).date()
    seq, y, m = [], today.year, today.month
    for _ in range(12):
        seq.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    seq.reverse()
    counts = [md.get((yy, mm), 0) for (yy, mm) in seq]
    total = sum(counts)
    maxc = max(counts) or 1
    n = len(seq)
    left, right, top, base = 20, 20, 56, 196
    innerW = W - left - right
    gap = 10
    barW = (innerW - gap * (n - 1)) / n
    barMaxH = base - top - 22
    out = [
        f'<text x="{left}" y="28" font-family="{SERIF}" font-size="18" class="t">每月贡献</text>',
        f'<text x="{W-right}" y="28" text-anchor="end" font-family="{MONO}" '
        f'font-size="11" letter-spacing="1" class="m">近 12 个月 · 合计 {total:,}</text>',
        f'<line x1="{left}" y1="40" x2="{W-right}" y2="40" class="hb"/>',
        f'<line x1="{left}" y1="{base}" x2="{W-right}" y2="{base}" class="hb"/>',
    ]
    for i, c in enumerate(counts):
        x = left + i * (barW + gap)
        bh = max(c / maxc * barMaxH, 2.0) if c > 0 else 0
        yb = base - bh
        out.append(
            f'<rect x="{x:.1f}" y="{yb:.1f}" width="{barW:.1f}" height="{bh:.1f}" '
            f'rx="2" fill="url(#barg)"><title>{seq[i][0]}年{seq[i][1]}月 · {c} 次</title></rect>')
        if c > 0:
            out.append(
                f'<text x="{x+barW/2:.1f}" y="{yb-6:.1f}" text-anchor="middle" '
                f'font-family="{MONO}" font-size="9" class="m">{c}</text>')
        else:
            out.append(
                f'<rect x="{x+barW/2-4:.1f}" y="{base-2}" width="8" height="2" class="h"/>')
        out.append(
            f'<text x="{x+barW/2:.1f}" y="{base+16:.1f}" text-anchor="middle" '
            f'font-family="{SANS}" font-size="10" class="d">{seq[i][1]}月</text>')
    return panel(base + 28, "".join(out))


def svg_weekday(d):
    """每周贡献节奏（周一到周日）—— 原生热力图不聚合到星期，互补。"""
    from collections import defaultdict
    wd = defaultdict(int)
    for day in d["days"]:
        wd[day["date"].isoweekday()] += day["count"]  # 1=周一 .. 7=周日
    labels = ["一", "二", "三", "四", "五", "六", "日"]
    counts = [wd.get(i, 0) for i in range(1, 8)]
    total = sum(counts)
    maxc = max(counts) or 1
    peak_i = max(range(1, 8), key=lambda i: wd.get(i, 0))
    n = 7
    left, right, top, base = 24, 24, 52, 150
    innerW = W - left - right
    gap = 18
    barW = (innerW - gap * (n - 1)) / n
    barMaxH = base - top - 16
    out = [
        f'<text x="{left}" y="28" font-family="{SERIF}" font-size="18" class="t">每周节奏</text>',
        f'<text x="{W-right}" y="28" text-anchor="end" font-family="{MONO}" '
        f'font-size="11" letter-spacing="1" class="m">一周 {total:,} 次 · 高峰 周{labels[peak_i-1]}</text>',
        f'<line x1="{left}" y1="40" x2="{W-right}" y2="40" class="hb"/>',
        f'<line x1="{left}" y1="{base}" x2="{W-right}" y2="{base}" class="hb"/>',
    ]
    for i, c in enumerate(counts):
        x = left + i * (barW + gap)
        bh = max(c / maxc * barMaxH, 3.0) if c > 0 else 0
        yb = base - bh
        out.append(
            f'<rect x="{x:.1f}" y="{yb:.1f}" width="{barW:.1f}" height="{bh:.1f}" '
            f'rx="2" fill="url(#barg)"><title>周{labels[i]} · {c} 次</title></rect>')
        out.append(
            f'<text x="{x+barW/2:.1f}" y="{base+16:.1f}" text-anchor="middle" '
            f'font-family="{SANS}" font-size="11" class="d">{labels[i]}</text>')
    return panel(base + 28, "".join(out))


def svg_year3d(d):
    """等距 3D 贡献日历（近 13 周特写，墨黑+金，透明底）—— 与原生全年热力图远近互补。"""
    days = d["days"][-91:]  # 近 13 周
    cells = [(i // 7, i % 7, day["count"]) for i, day in enumerate(days)]

    def level(c):
        if c == 0:
            return 0
        if c <= 2:
            return 1
        if c <= 5:
            return 2
        if c <= 9:
            return 3
        return 4

    H_BY_LV = [0, 12, 26, 42, 58]  # 0 = 平铺地砖
    hw, hh = 13.0, 6.5
    polys = []
    for c, r, cnt in cells:
        lv = level(cnt)
        h = H_BY_LV[lv]
        bx = (c - r) * hw
        by = (c + r) * hh
        if h <= 0:
            tw, th = hw * 0.62, hh * 0.62  # 内缩淡地砖，降噪
            pts = (f'{bx:.1f},{by-th:.1f} {bx+tw:.1f},{by:.1f} '
                   f'{bx:.1f},{by+th:.1f} {bx-tw:.1f},{by:.1f}')
            polys.append((c + r, f'<polygon points="{pts}" class="hf"/>'))
        else:
            tT = (bx, by - hh - h); tR = (bx + hw, by - h); tB = (bx, by + hh - h); tL = (bx - hw, by - h)
            top = (f'{tT[0]:.1f},{tT[1]:.1f} {tR[0]:.1f},{tR[1]:.1f} '
                   f'{tB[0]:.1f},{tB[1]:.1f} {tL[0]:.1f},{tL[1]:.1f}')
            left = (f'{bx-hw:.1f},{by:.1f} {bx:.1f},{by+hh:.1f} '
                    f'{tB[0]:.1f},{tB[1]:.1f} {tL[0]:.1f},{tL[1]:.1f}')
            right = (f'{bx+hw:.1f},{by:.1f} {bx:.1f},{by+hh:.1f} '
                     f'{tB[0]:.1f},{tB[1]:.1f} {tR[0]:.1f},{tR[1]:.1f}')
            polys.append((c + r,
                f'<polygon points="{top}" fill="url(#barg)"/>'
                f'<polygon points="{left}" class="gd"/>'
                f'<polygon points="{right}" class="gs"/>'))
    polys.sort(key=lambda p: p[0])  # 后→前 画家算法
    # 月份坐标：水平轴置于网格下方（不随等距投影斜漂）
    mlabels, prev_m, ncols = [], None, len(days) // 7
    for c in range(ncols):
        if c * 7 >= len(days):
            break
        m = days[c * 7]["date"].month
        if m != prev_m:
            mlabels.append(((c - 6) * hw, f"{m}月"))
            prev_m = m
    axis_y = ((ncols - 1) + 6) * hh + hh + 24
    axis = (f'<line x1="{(0 - 6) * hw - hw:.1f}" y1="{axis_y - 9:.1f}" '
            f'x2="{((ncols - 1) - 6) * hw + hw:.1f}" y2="{axis_y - 9:.1f}" class="hb"/>')
    mtxt = "".join(
        f'<text x="{x:.1f}" y="{axis_y:.1f}" text-anchor="middle" font-family="{SANS}" '
        f'font-size="10.5" class="d">{esc(lbl)}</text>' for x, lbl in mlabels)
    inner = "".join(p[1] for p in polys) + axis + mtxt
    xs, ys = [], []
    for c, r, cnt in cells:
        bx = (c - r) * hw; by = (c + r) * hh; h = H_BY_LV[level(cnt)]
        for px, py in [(bx, by - hh - h), (bx + hw, by), (bx, by + hh), (bx - hw, by - h)]:
            xs.append(px); ys.append(py)
    for x, _lbl in mlabels:
        xs.append(x); ys.append(axis_y)
    pad = 16
    vbx = min(xs) - pad; vby = min(ys) - pad
    vbw = (max(xs) - min(xs)) + 2 * pad; vbh = (max(ys) - min(ys)) + 2 * pad
    W3, H3 = 720, int(round(720 * vbh / vbw))
    defs = ('<defs><linearGradient id="barg" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="var(--goldhi)"/>'
            '<stop offset="1" stop-color="var(--gold)"/></linearGradient></defs>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W3}" height="{H3}" '
           f'viewBox="{vbx:.1f} {vby:.1f} {vbw:.1f} {vbh:.1f}" fill="none" '
           f'style="max-width:100%;height:auto">' + defs + STYLE + inner + "</svg>")
    validate(svg, "YEAR3D")
    return svg


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
    h = 100
    out = []
    per_row = 4
    for i, (lang, size) in enumerate(top):
        row, col = divmod(i, per_row)
        lx = col * (W / per_row)
        ly = 38 + row * 36
        pct = size / total * 100
        c = LANG_COLORS.get(lang, FALLBACK)
        out.append(
            f'<circle cx="{lx + 6}" cy="{ly - 4}" r="4.5" fill="{c}"/>'
            f'<text x="{lx + 18}" y="{ly}" font-family="{SANS}" font-size="13" '
            f'class="t">{esc(lang)}</text>'
            f'<text x="{lx + 18}" y="{ly + 15}" font-family="{MONO}" font-size="10" '
            f'class="m">{pct:.1f}%</text>')
    return panel(h, "".join(out))


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
                f'class="hb"/>'
                f'<text x="{x + w/2:.1f}" y="{y + 20}" text-anchor="middle" '
                f'font-family="{SANS}" font-size="12.5" class="t">{esc(s)}</text>')
            x += w + h_gap
    return panel(h, "".join(out))


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
    # 连续同仓库同类型事件折叠为一条，避免刷屏式重复
    groups = []
    for e in d["events"]:
        key = (e["type"], e["repo"]["name"])
        if groups and (groups[-1][0]["type"], groups[-1][0]["repo"]["name"]) == key:
            groups[-1].append(e)
        else:
            groups.append([e])
    groups = groups[:limit]
    if not groups:
        return ""
    row_h = 30
    h = len(groups) * row_h + 10
    now = datetime.now(TZ)
    out = []
    for i, g in enumerate(groups):
        e = g[0]
        repo = e["repo"]["name"].split("/")[-1]
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
        txt = event_text(e)
        if len(g) > 1:
            if e["type"] == "PushEvent":
                commits = sum(len((x.get("payload") or {}).get("commits") or []) for x in g)
                txt = (f"向 {repo} 推送 {len(g)} 次 · 共 {commits} 个提交"
                       if commits else f"向 {repo} 推送 {len(g)} 次")
            else:
                txt = f"{txt} ×{len(g)}"
        out.append(
            f'<circle cx="10" cy="{y - 4}" r="3" class="g"/>'
            f'<text x="26" y="{y}" font-family="{SANS}" font-size="13" class="t">'
            f'{esc(txt)}</text>'
            f'<text x="{W}" y="{y}" text-anchor="end" font-family="{MONO}" '
            f'font-size="11" class="m">{esc(ago)}</text>')
        if i < len(groups) - 1:
            out.append(f'<rect x="10" y="{y + 9}" width="1" height="11" class="h"/>')
    return panel(h, "".join(out))


def svg_footer():
    h = 46
    inner = (
        f'<rect x="120" y="14" width="{W-240}" height="1" class="h"/>'
        f'<text x="{W/2}" y="32" text-anchor="middle" font-family="{MONO}" '
        f'font-size="11" letter-spacing="1" class="m">Crafted with restraint · 2026</text>'
    )
    return panel(h, inner)


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
        "GRAPH": svg_monthly(d),
        "WEEKDAY": svg_weekday(d),
        "YEAR3D": svg_year3d(d),
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
               "GRAPH": "每月贡献柱状图", "WEEKDAY": "每周贡献节奏", "YEAR3D": "近 13 周贡献 3D", "LANGS": "语言分布", "SKILLS": "技术栈",
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
    for k in ["HEADER", "MANIFESTO", "STATS", "GRAPH", "WEEKDAY", "YEAR3D", "LANGS", "SKILLS", "FEED", "FOOTER"]:
        prev.append(f"<div style='border-radius:8px;overflow:hidden'>"
                    f"<img src='{data_uri(parts[k])}' style='width:100%;display:block'/></div>")
    prev.append("</div></body>")
    with open(os.path.join(ROOT, "preview.html"), "w", encoding="utf-8") as f:
        f.write("".join(prev))

    print(f"README 已生成 | 贡献 {stats['total']} · 仓库 {stats['repos']} · "
          f"最长连续 {longest} 天 · 当前连续 {current} 天")


if __name__ == "__main__":
    main()
