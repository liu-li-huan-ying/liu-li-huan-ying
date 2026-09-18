#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GitHub 主页 README —— 自制 SVG 片段（零外部依赖），「墨黑 · 哑光金 · 朱砂印」。

设计语言：
  - 案头感：宋体抬头 + 字距化英文小标 + 通栏发丝线，每张卡片同一个「抬头」结构。
  - 单一强调色（哑光金）压不住场，补第二强调色朱砂（印章、峰值标记），只出现在三处。
  - 所有 SVG 透明底、无外壳 —— 直接画在 GitHub 容器上，避免「框中框」。
  - 内置 prefers-color-scheme 明暗双配色（CSS 变量 + @media）。
  - 不引外部图片：头像位用自绘朱砂印章，SVG-as-img 里外链图片会被 GitHub 拦掉。

用法: python scripts/generate.py   （需 gh 已登录或设置 GITHUB_TOKEN）
输出: README.md / assets/*.svg / preview.html
"""

import base64
import json
import math
import os
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone

USER = "liu-li-huan-ying"
W = 720   # 容器宽度
GUT = 24  # 通栏留白
RULE = 46  # 抬头底线 y

SERIF = ("'Georgia','Songti SC','STSong','Noto Serif SC','Source Han Serif SC',"
         "'SimSun',serif")
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

# 工具箱按用途分组，而不是平铺一长串标签
SKILL_GROUPS = [
    ("前端", ["JavaScript", "TypeScript", "Vue 3", "React Native", "HTML / CSS"]),
    ("系统", ["Go", "C++", "Rust", "Node.js", "Linux"]),
    ("工具", ["Git", "Docker", "Chrome 扩展", "Obsidian 插件"]),
]

TZ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

# —— 双配色令牌：暗色为默认，亮色 GitHub 整套翻掉 ——
DARK = dict(text="#ECEAE4", dim="#9AA3AE", mute="#6B7280", hair="#242C38",
            gold="#C8A97E", goldhi="#DCC096", soft="#E6D2B0",
            seal="#B0413E", sealink="#F6F1E8")
LIGHT = dict(text="#1F2328", dim="#57606A", mute="#8A94A0", hair="#D6DCE3",
             gold="#8F6B33", goldhi="#A57E42", soft="#7D5E30",
             seal="#A03A34", sealink="#FCF8F2")


def _vars(tokens, sel):
    return sel + "{" + "".join(f"--{k}:{v};" for k, v in tokens.items()) + "}"


STYLE = (
    "<style>"
    + _vars(DARK, ":root")
    + "@media (prefers-color-scheme: light){" + _vars(LIGHT, ":root") + "}"
    + ".t{fill:var(--text)}.d{fill:var(--dim)}.m{fill:var(--mute)}"
      ".g{fill:var(--gold)}.s{fill:var(--soft)}"
      ".h{fill:var(--hair)}"
      ".hb{fill:none;stroke:var(--hair);stroke-width:1}"
      ".seal{fill:var(--seal)}.sealt{fill:var(--sealink)}"
      ".gs{fill:var(--gold);opacity:.72}.gd{fill:var(--gold);opacity:.45}"
      ".grid{fill:none;stroke:var(--hair);stroke-width:1;stroke-dasharray:2 5}"
    "</style>"
)


# ---------------------------------------------------------------- 工具

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tw(s, size):
    """粗略文本宽度：CJK 按 1em，拉丁按 0.55em。"""
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in s) * size


def clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


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


DEFS = (
    '<defs>'
    '<linearGradient id="barg" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="var(--goldhi)"/>'
    '<stop offset="1" stop-color="var(--gold)"/></linearGradient>'
    '<linearGradient id="area" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="var(--gold)" stop-opacity=".38"/>'
    '<stop offset="1" stop-color="var(--gold)" stop-opacity="0"/></linearGradient>'
    '</defs>'
)


def panel(h, inner):
    return svg_open(h) + DEFS + STYLE + inner + "</svg>"


def plate(cn, en, meta=""):
    """统一卡片抬头：金竖标 + 宋体题名 + 字距化英文 + 右对齐元信息 + 通栏发丝线。"""
    out = [
        f'<rect x="{GUT}" y="{RULE - 15}" width="2" height="14" class="g"/>',
        f'<text x="{GUT + 11}" y="{RULE - 1}" font-family="{SERIF}" '
        f'font-size="17" class="t">{esc(cn)}</text>',
        f'<text x="{GUT + 11 + tw(cn, 17) + 11}" y="{RULE - 2}" '
        f'font-family="{MONO}" font-size="9" letter-spacing="2.5" class="m">'
        f'{esc(en)}</text>',
    ]
    if meta:
        out.append(
            f'<text x="{W - GUT}" y="{RULE - 2}" text-anchor="end" '
            f'font-family="{MONO}" font-size="10" letter-spacing=".4" class="d">'
            f'{esc(meta)}</text>')
    out.append(f'<rect x="{GUT}" y="{RULE}" width="{W - GUT * 2}" height="1" class="h"/>')
    return "".join(out)


def seal_mark(x, y, size, ch="琉"):
    """朱砂印：阴文方印 + 内框，纯手绘，不依赖外部图片。"""
    return (
        f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="2.5" class="seal"/>'
        f'<rect x="{x + size * .09:.1f}" y="{y + size * .09:.1f}" '
        f'width="{size * .82:.1f}" height="{size * .82:.1f}" rx="1.5" '
        f'fill="none" stroke="var(--sealink)" stroke-opacity=".5" stroke-width="1"/>'
        f'<text x="{x + size / 2:.1f}" y="{y + size * .72:.1f}" text-anchor="middle" '
        f'font-family="{SERIF}" font-size="{size * .56:.1f}" font-weight="700" '
        f'class="sealt">{esc(ch)}</text>'
    )


# ---------------------------------------------------------------- 数据

def fetch_all():
    token = get_token()
    if not token:
        print("[FATAL] 拿不到 GitHub token：请 gh auth login 或设置 GITHUB_TOKEN",
              file=sys.stderr)
        sys.exit(1)

    user = api_get(f"https://api.github.com/users/{USER}", token)
    repos = api_get(f"https://api.github.com/users/{USER}/repos?per_page=100&sort=updated", token)
    events = api_get(f"https://api.github.com/users/{USER}/events/public?per_page=60", token)

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

def svg_header(d):
    u = d["user"]
    since = (u.get("created_at") or "")[:4]
    h = 104
    name = "琉璃幻影"
    nx = GUT + 46 + 18
    out = [
        seal_mark(GUT, 26, 46),
        f'<text x="{nx}" y="52" font-family="{SERIF}" font-size="32" class="t">'
        f'{esc(name)}</text>',
        f'<text x="{nx + tw(name, 32) + 14}" y="51" font-family="{MONO}" '
        f'font-size="9.5" letter-spacing="3" class="g">INDEPENDENT BUILDER</text>',
        f'<text x="{nx}" y="74" font-family="{SANS}" font-size="12.5" class="d">'
        f'独立开发者 · 造趁手的工具</text>',
        f'<text x="{W - GUT}" y="40" text-anchor="end" font-family="{MONO}" '
        f'font-size="10" class="m">China · UTC+8</text>',
        f'<text x="{W - GUT}" y="57" text-anchor="end" font-family="{MONO}" '
        f'font-size="10" class="m">GitHub since {esc(since)}</text>',
        f'<text x="{W - GUT}" y="74" text-anchor="end" font-family="{MONO}" '
        f'font-size="10" class="m">每日 08:00 自动更新</text>',
        f'<rect x="{GUT}" y="92" width="{W - GUT * 2}" height="1" class="h"/>',
    ]
    return panel(h, "".join(out))


def svg_manifesto():
    h = 106
    out = [
        plate("宣言", "MANIFESTO"),
        f'<text x="{W / 2}" y="80" text-anchor="middle" font-family="{SERIF}" '
        f'font-size="19" class="t">我造工具，先为自己，也为同样挑剔的人。</text>',
        f'<text x="{W / 2}" y="98" text-anchor="middle" font-family="{SANS}" '
        f'font-size="11.5" font-style="italic" class="m">'
        f'Tools I build for myself first — then for people just as picky.</text>',
    ]
    return panel(h, "".join(out))


def svg_stats(stats):
    cols = 4
    colw = (W - GUT * 2) / cols
    h = 122
    items = [
        ("总贡献", f"{stats['total']:,}", ""),
        ("公开仓库", str(stats["repos"]), ""),
        ("最长连续", f"{stats['longest']}", "天"),
        ("当前连续", f"{stats['current']}", "天"),
    ]
    out = [plate("数据", "BY THE NUMBERS",
                 f"近 12 个月 · 合计 ★ {stats['stars']}")]
    for i in range(1, cols):
        out.append(f'<rect x="{GUT + i * colw:.0f}" y="64" width="1" height="46" class="h"/>')
    for i, (label, val, unit) in enumerate(items):
        cx = GUT + (i + 0.5) * colw
        out.append(
            f'<text x="{cx:.0f}" y="98" text-anchor="middle" font-family="{SERIF}" '
            f'font-size="30" class="t">{esc(val)}</text>'
            f'<text x="{cx + tw(val, 30) / 2 + 5:.0f}" y="98" font-family="{SANS}" '
            f'font-size="11" class="m">{esc(unit)}</text>'
            f'<text x="{cx:.0f}" y="114" text-anchor="middle" font-family="{MONO}" '
            f'font-size="9.5" letter-spacing="2" class="d">{esc(label)}</text>')
    return panel(h, "".join(out))


def bar_path(x, top, w, h, base, r=3.0):
    """柱形路径：只圆顶部 + 平底贴基线（rect 的 rx 会把底角也圆掉，很廉价）。"""
    r = min(r, w / 2, h)
    return (f'M{x:.1f},{base:.1f} L{x:.1f},{top + r:.1f} '
            f'Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} '
            f'L{x + w - r:.1f},{top:.1f} '
            f'Q{x + w:.1f},{top:.1f} {x + w:.1f},{top + r:.1f} '
            f'L{x + w:.1f},{base:.1f} Z')


def svg_trend(d):
    """近 60 天日粒度面积图 + 7 日均线 —— 替掉「12 根柱里 10 根是空的」年度柱图。"""
    days = d["days"][-60:]
    counts = [x["count"] for x in days]
    tot = sum(counts)
    top = 66
    base = 158
    plotH = base - top
    x0, x1 = GUT, W - GUT
    step = (x1 - x0) / (len(days) - 1)
    maxc = max(counts) or 1
    scale = plotH / (maxc * 1.12)

    pts = [(x0 + i * step, base - c * scale) for i, c in enumerate(counts)]
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"M{x0:.1f},{base:.1f} L" + " L".join(
        f"{x:.1f},{y:.1f}" for x, y in pts) + f" L{x1:.1f},{base:.1f} Z"

    ma = []
    for i in range(len(counts)):
        win = counts[max(0, i - 6):i + 1]
        ma.append((x0 + i * step, base - (sum(win) / len(win)) * scale))
    maline = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in ma)

    out = [
        plate("近 60 天", "DAILY",
              f"合计 {tot:,} · 日均 {tot / len(counts):.1f} · 峰值 {maxc}"),
        f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{base}" class="hb"/>',
    ]
    for i, day in enumerate(days):
        if i and day["date"].month != days[i - 1]["date"].month:
            x = x0 + i * step
            out.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{base}" class="grid"/>')
            out.append(
                f'<text x="{x + 3:.1f}" y="{base + 16}" font-family="{MONO}" '
                f'font-size="9.5" class="m">{day["date"].month}月</text>')
    out.append(f'<path d="{area}" fill="url(#area)"/>')
    out.append(f'<path d="{line}" stroke="var(--gold)" stroke-width="1.4" '
               f'stroke-linejoin="round"/>')
    out.append(f'<path d="{maline}" stroke="var(--dim)" stroke-width="1" '
               f'stroke-dasharray="3 4" stroke-opacity=".85"/>')
    pi = max(range(len(counts)), key=lambda i: counts[i])
    px, py = pts[pi]
    out.append(
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.8" class="seal"/>'
        f'<text x="{px:.1f}" y="{py - 8:.1f}" text-anchor="middle" '
        f'font-family="{MONO}" font-size="10" class="d">{maxc}</text>')
    out.append(
        f'<text x="{x0}" y="{base + 30}" font-family="{MONO}" font-size="9" '
        f'letter-spacing="1.5" class="m">{days[0]["date"]:%m-%d} — '
        f'{days[-1]["date"]:%m-%d}</text>')
    out.append(
        f'<text x="{x1}" y="{base + 30}" text-anchor="end" font-family="{MONO}" '
        f'font-size="9" letter-spacing="1.5" class="m">— — 7 日均线</text>')
    return panel(base + 40, "".join(out))


def svg_weekday(d):
    """每周贡献节奏（周一到周日）。"""
    wd = defaultdict(int)
    for day in d["days"]:
        wd[day["date"].isoweekday()] += day["count"]  # 1=周一 .. 7=周日
    labels = ["一", "二", "三", "四", "五", "六", "日"]
    counts = [wd.get(i, 0) for i in range(1, 8)]
    total = sum(counts)
    maxc = max(counts) or 1
    peak_i = max(range(1, 8), key=lambda i: wd.get(i, 0))
    barW, gap = 44.0, 40.0
    left = (W - (7 * barW + 6 * gap)) / 2
    top, base = 68, 156
    plotH = base - top
    out = [
        plate("每周节奏", "WEEKDAY", f"一周 {total:,} 次 · 高峰 周{labels[peak_i - 1]}"),
        f'<line x1="{GUT}" y1="{base}" x2="{W - GUT}" y2="{base}" class="hb"/>',
    ]
    for f in (0.5, 1.0):
        y = base - plotH * f
        out.append(f'<line x1="{GUT}" y1="{y:.1f}" x2="{W - GUT}" y2="{y:.1f}" class="grid"/>')
    for i, c in enumerate(counts):
        x = left + i * (barW + gap)
        cx = x + barW / 2
        if c > 0:
            bh = c / maxc * plotH
            out.append(
                f'<path d="{bar_path(x, base - bh, barW, bh, base)}" fill="url(#barg)">'
                f'<title>周{labels[i]} · {c} 次</title></path>')
            out.append(
                f'<text x="{cx:.1f}" y="{base - bh - 7:.1f}" text-anchor="middle" '
                f'font-family="{MONO}" font-size="9.5" class="m">{c}</text>')
        else:
            out.append(f'<rect x="{cx - 5:.1f}" y="{base - 2}" width="10" height="1" class="h"/>')
        is_peak = (i + 1) == peak_i
        out.append(
            f'<text x="{cx:.1f}" y="{base + 18}" text-anchor="middle" '
            f'font-family="{SANS}" font-size="11.5" class="{"t" if is_peak else "d"}">'
            f'{labels[i]}</text>')
        if is_peak:
            out.append(f'<rect x="{cx - 2:.1f}" y="{base + 25}" width="4" height="4" '
                       f'transform="rotate(45 {cx:.1f} {base + 27})" class="seal"/>')
    return panel(base + 40, "".join(out))


def svg_year3d(d):
    """等距 3D 贡献日历（近 13 周）。左列读数 + 图例，右列方块 —— 月份轴按周心算，
    不再沿斜轴水平漂（旧版「6月 7月」挤成一团就是这个 bug）。"""
    days = list(d["days"][-91:])
    pad = days[0]["date"].isoweekday() - 1  # 补齐到周一，列才是真周
    cells = [(0, 0, 0, None)] * pad + [
        (i // 7, i % 7, day["count"], day["date"]) for i, day in enumerate(days)]
    cells += [(0, 0, 0, None)] * (-len(cells) % 7)  # 补齐末周，行数才齐
    ncols = len(cells) // 7

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

    H_BY_LV = [0, 8, 17, 27, 38]
    hw, hh = 11.0, 5.5
    spanW = (ncols + 7) * hw          # 等距网格水平占位（含菱形两翼）
    spanH = (ncols + 5) * hh + 2 * hh + max(H_BY_LV)
    availX, availW = 282, W - 282 - GUT
    top, availH = 62, 232
    s = min(availW / spanW, availH / spanH)
    hw, hh = hw * s, hh * s
    hs = [x * s for x in H_BY_LV]
    ox = availX + (availW - (ncols + 7) * hw) / 2 + 6 * hw
    oy = top + (availH - spanH * s) / 2 + hh + hs[-1]

    def px(c, r):
        return ox + (c - r) * hw, oy + (c + r) * hh

    # 地平面：一整块淡金平行四边形 + 网格线，替掉原先一片片「脏地砖」
    g0, g1, g2, g3 = px(0, 0), px(ncols - 1, 0), px(ncols - 1, 6), px(0, 6)
    ground = "".join(
        f'<polygon points="{g0[0]:.1f},{g0[1] - hh:.1f} {g1[0]:.1f},{g1[1]:.1f} '
        f'{g2[0]:.1f},{g2[1] + hh:.1f} {g3[0]:.1f},{g3[1]:.1f}" '
        f'fill="var(--gold)" fill-opacity=".05"/>'
        f'<polygon points="{g0[0]:.1f},{g0[1] - hh:.1f} {g1[0]:.1f},{g1[1]:.1f} '
        f'{g2[0]:.1f},{g2[1] + hh:.1f} {g3[0]:.1f},{g3[1]:.1f}" class="hb" '
        f'stroke-opacity=".5"/>')
    rules = []
    for c in range(ncols):
        a, b = px(c, 0), px(c, 6)
        rules.append(f'<line x1="{a[0]:.1f}" y1="{a[1] - hh:.1f}" x2="{b[0]:.1f}" '
                     f'y2="{b[1] - hh:.1f}" class="hb" stroke-opacity=".22"/>')
    for r in range(7):
        a, b = px(0, r), px(ncols - 1, r)
        rules.append(f'<line x1="{a[0]:.1f}" y1="{a[1] - hh:.1f}" x2="{b[0]:.1f}" '
                     f'y2="{b[1] - hh:.1f}" class="hb" stroke-opacity=".22"/>')

    polys = []
    for c, r, cnt, _dt in cells:
        lv = level(cnt)
        h = hs[lv]
        if h <= 0:
            continue
        bx, by = px(c, r)
        tT = (bx, by - hh - h); tR = (bx + hw, by - h)
        tB = (bx, by + hh - h); tL = (bx - hw, by - h)
        top_p = (f'{tT[0]:.1f},{tT[1]:.1f} {tR[0]:.1f},{tR[1]:.1f} '
                 f'{tB[0]:.1f},{tB[1]:.1f} {tL[0]:.1f},{tL[1]:.1f}')
        left_p = (f'{bx - hw:.1f},{by:.1f} {bx:.1f},{by + hh:.1f} '
                  f'{tB[0]:.1f},{tB[1]:.1f} {tL[0]:.1f},{tL[1]:.1f}')
        right_p = (f'{bx + hw:.1f},{by:.1f} {bx:.1f},{by + hh:.1f} '
                   f'{tB[0]:.1f},{tB[1]:.1f} {tR[0]:.1f},{tR[1]:.1f}')
        polys.append((c + r,
                      f'<polygon points="{top_p}" fill="url(#barg)">'
                      f'<title>{_dt:%m-%d} · {cnt} 次</title></polygon>'
                      f'<polygon points="{left_p}" class="gd"/>'
                      f'<polygon points="{right_p}" class="gs"/>'))
    polys.sort(key=lambda p: p[0])  # 后→前 画家算法

    # 月份刻度：放在「周列」的水平中心，且必须落在最前排方块之下
    axis_y = oy + (ncols - 1 + 6) * hh + hh + 18
    mlabels, prev_m = [], None
    for c in range(ncols):
        mid = cells[c * 7 + 6][3]  # 该周周三，用来判月份归属
        if mid and mid.month != prev_m:
            mlabels.append((ox + (c - 3) * hw, f"{mid.month}月"))
            prev_m = mid.month
    out = [ground, "".join(rules), "".join(p[1] for p in polys)]
    if mlabels:
        out.append(f'<line x1="{mlabels[0][0] - hw:.1f}" y1="{axis_y - 12:.1f}" '
                   f'x2="{mlabels[-1][0] + hw:.1f}" y2="{axis_y - 12:.1f}" class="hb"/>')
    for x, lbl in mlabels:
        out.append(f'<rect x="{x - .5:.1f}" y="{axis_y - 12:.1f}" width="1" height="4" class="h"/>')
        out.append(f'<text x="{x:.1f}" y="{axis_y + 1:.1f}" text-anchor="middle" '
                   f'font-family="{MONO}" font-size="9.5" class="m">{esc(lbl)}</text>')

    # 左列：读数 + 高度图例
    tot = sum(x[2] for x in cells)
    active = sum(1 for x in cells if x[2] > 0)
    wk = defaultdict(int)
    for c, _, cnt, _dt in cells:
        wk[c] += cnt
    best = max(wk.values()) if wk else 0
    active_wk = sum(1 for c in wk.values() if c > 0)
    rows = [("近 13 周合计", f"{tot:,}"), ("活跃天数", f"{active}"),
            ("活跃周数", f"{active_wk}/13"), ("最活跃一周", f"{best}")]
    for i, (label, val) in enumerate(rows):
        y = 82 + i * 40
        out.append(
            f'<text x="{GUT}" y="{y}" font-family="{SERIF}" font-size="26" '
            f'class="t">{esc(val)}</text>'
            f'<text x="{GUT}" y="{y + 14}" font-family="{MONO}" font-size="9.5" '
            f'letter-spacing="1.5" class="d">{esc(label)}</text>')
    ly = 82 + len(rows) * 40 + 12
    steps = [("0", 0), ("1-2", 1), ("3-5", 2), ("6-9", 3), ("10+", 4)]
    for i, (lbl, lv) in enumerate(steps):
        x = GUT + i * 48
        hgt = max(3, hs[lv] * 0.55)
        out.append(
            f'<rect x="{x}" y="{ly + 14 - hgt:.1f}" width="14" height="{hgt:.1f}" '
            f'rx="1.5" class="gs"/>'
            f'<text x="{x + 7:.1f}" y="{ly + 26}" text-anchor="middle" '
            f'font-family="{MONO}" font-size="8.5" class="m">{esc(lbl)}</text>')
    out.append(f'<text x="{GUT}" y="{ly - 4}" font-family="{MONO}" font-size="9" '
               f'letter-spacing="2" class="m">单日贡献 → 柱高</text>')

    head = plate("近 13 周", "ISOMETRIC", "方块越高 = 当天提交越多")
    return panel(int(axis_y + 22), head + "".join(out))


def svg_langs(d):
    repos = [r for r in d["repos"] if not r.get("fork") and r.get("language")]
    agg = {}
    for r in repos:
        agg[r["language"]] = agg.get(r["language"], 0) + (r.get("size") or 0)
    if not agg:
        return ""
    total = sum(agg.values())
    top = sorted(agg.items(), key=lambda kv: -kv[1])[:8]
    maxpct = top[0][1] / total * 100

    bar_y, bar_h = 62, 9
    out = [plate("语言构成", "BY BYTES", f"{len(repos)} 个仓库 · 按字节数")]
    x = GUT
    for i, (lang, size) in enumerate(top):
        seg = (W - GUT * 2) * size / total
        gap = 2 if i < len(top) - 1 else 0
        out.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{max(seg - gap, 1):.1f}" '
                   f'height="{bar_h}" rx="2" fill="{LANG_COLORS.get(lang, FALLBACK)}">'
                   f'<title>{esc(lang)} {size / total * 100:.1f}%</title></rect>')
        x += seg
    cellW = (W - GUT * 2 - 28) / 2
    maxBar = cellW - 120 - 46
    for i, (lang, size) in enumerate(top):
        col, row = i % 2, i // 2
        cx = GUT + col * (cellW + 28)
        cy = bar_y + bar_h + 26 + row * 30
        pct = size / total * 100
        c = LANG_COLORS.get(lang, FALLBACK)
        out.append(
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="4" fill="{c}"/>'
            f'<text x="{cx + 17}" y="{cy}" font-family="{SANS}" font-size="12" '
            f'class="t">{esc(lang)}</text>'
            f'<rect x="{cx + 120}" y="{cy - 8}" width="{maxBar:.1f}" height="3" '
            f'rx="1.5" class="h"/>'
            f'<rect x="{cx + 120}" y="{cy - 8}" width="{maxBar * pct / maxpct:.1f}" '
            f'height="3" rx="1.5" fill="{c}"/>'
            f'<text x="{cx + cellW:.1f}" y="{cy}" text-anchor="end" '
            f'font-family="{MONO}" font-size="10" class="d">{pct:.1f}%</text>')
    rows = math.ceil(len(top) / 2)
    return panel(bar_y + bar_h + 34 + rows * 30, "".join(out))


def svg_skills():
    out = [plate("工具箱", "TOOLBOX", "按用途分，不按热度排")]
    y = RULE + 22
    for label, items in SKILL_GROUPS:
        out.append(f'<text x="{GUT}" y="{y + 17}" font-family="{MONO}" font-size="9.5" '
                   f'letter-spacing="2" class="g">{esc(label)}</text>')
        x = GUT + 62
        for s in items:
            w = tw(s, 12) + 22
            if x + w > W - GUT:
                continue
            out.append(
                f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="26" rx="3" class="hb"/>'
                f'<text x="{x + w / 2:.1f}" y="{y + 17}" text-anchor="middle" '
                f'font-family="{SANS}" font-size="12" class="t">{esc(s)}</text>')
            x += w + 9
        y += 38
    return panel(y + 2, "".join(out))


def svg_repos(d):
    # 个人主页仓库本身不算「作品」，从矩阵里剔掉
    skip = {USER, f"{USER}.github.io"}
    repos = [r for r in d["repos"] if not r.get("fork") and r["name"] not in skip]
    if not repos:
        return ""
    repos.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    repos.sort(key=lambda r: -r["stargazers_count"])  # 稳定排序：星标优先，同级看新旧
    shown = repos[:10]
    stars = sum(r["stargazers_count"] for r in repos)
    cols, tileH, gap = 5, 52, 10
    tileW = (W - GUT * 2 - (cols - 1) * gap) / cols
    out = [plate("仓库矩阵", "REPOSITORIES",
                 f"{len(repos)} 个作品仓库 · 合计 ★ {stars}")]
    for i, r in enumerate(shown):
        col, row = i % cols, i // cols
        x = GUT + col * (tileW + gap)
        y = RULE + 20 + row * (tileH + gap)
        lang = r.get("language") or ""
        c = LANG_COLORS.get(lang, FALLBACK)
        n = r["stargazers_count"]
        pushed = (r.get("pushed_at") or "")[2:10]  # 26-09-18
        right = (f'<text x="{x + tileW - 10:.1f}" y="{y + 38}" text-anchor="end" '
                 f'font-family="{MONO}" font-size="9.5" class="g">★ {n}</text>') if n else (
                 f'<text x="{x + tileW - 10:.1f}" y="{y + 38}" text-anchor="end" '
                 f'font-family="{MONO}" font-size="9" class="m">{esc(pushed)}</text>')
        out.append(
            f'<rect x="{x:.1f}" y="{y}" width="{tileW:.1f}" height="{tileH}" '
            f'rx="3" class="hb"/>'
            f'<text x="{x + 10:.1f}" y="{y + 21}" font-family="{MONO}" '
            f'font-size="10.5" class="t">{esc(clip(r["name"], 17))}</text>'
            f'<circle cx="{x + 13:.1f}" cy="{y + 35}" r="3.2" fill="{c}"/>'
            f'<text x="{x + 21:.1f}" y="{y + 38}" font-family="{SANS}" '
            f'font-size="9.5" class="m">{esc(lang)}</text>' + right)
    rows = math.ceil(len(shown) / cols)
    return panel(RULE + 20 + rows * (tileH + gap) + 4, "".join(out))


TYPE_LABEL = {
    "PushEvent": "推送", "CreateEvent": "新建", "DeleteEvent": "删除",
    "ReleaseEvent": "发布", "PullRequestEvent": "PR", "IssuesEvent": "议题",
    "IssueCommentEvent": "评论", "ForkEvent": "派生", "WatchEvent": "Star",
    "PublicEvent": "转为公开", "MemberEvent": "加入", "GollumEvent": "Wiki",
    "CommitCommentEvent": "提交评论",
}


def parse_at(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)


def ago(t, now):
    delta = now - t
    if delta.days == 0:
        return "今天"
    if delta.days == 1:
        return "昨天"
    if delta.days < 30:
        return f"{delta.days} 天前"
    return f"{delta.days // 30} 个月前"


def svg_feed(d, limit=6):
    """按仓库折叠统计，而不是逐条罗列 —— 逐条会把整张卡片喂给同一批推送。"""
    by = {}
    for e in d["events"]:
        repo = e["repo"]["name"].split("/")[-1]
        g = by.setdefault(repo, {"types": defaultdict(int), "commits": 0, "last": None})
        g["types"][e["type"]] += 1
        t = parse_at(e["created_at"])
        if g["last"] is None or t > g["last"]:
            g["last"] = t
        if e["type"] == "PushEvent":
            g["commits"] += len((e.get("payload") or {}).get("commits") or [])
    rows = sorted(by.items(), key=lambda kv: kv[1]["last"], reverse=True)[:limit]
    if not rows:
        return ""
    now = datetime.now(TZ)
    maxn = max(sum(g["types"].values()) for _, g in rows)
    row_h = 32
    y0 = RULE + 28
    out = [plate("近期投入", "RECENT WORK", f"近 {len(d['events'])} 条事件 · 按仓库折叠")]
    for i, (repo, g) in enumerate(rows):
        y = y0 + i * row_h
        n = sum(g["types"].values())
        parts = [f"{TYPE_LABEL.get(t, t)} {c} 次" for t, c in
                 sorted(g["types"].items(), key=lambda kv: -kv[1])]
        if g["commits"]:
            parts.append(f"{g['commits']} 个提交")
        out.append(
            f'<text x="{GUT}" y="{y}" font-family="{MONO}" font-size="12" '
            f'class="g">{esc(clip(repo, 21))}</text>'
            f'<text x="{GUT + 156}" y="{y}" font-family="{SANS}" font-size="12" '
            f'class="t">{esc(" · ".join(parts))}</text>'
            f'<text x="{W - GUT}" y="{y}" text-anchor="end" font-family="{MONO}" '
            f'font-size="10" class="m">{esc(ago(g["last"], now))}</text>'
            f'<rect x="{GUT + 156}" y="{y + 8}" width="{(W - GUT * 2 - 156) * n / maxn:.1f}" '
            f'height="1.5" class="gs"/>')
    return panel(y0 + len(rows) * row_h + 4, "".join(out))


def svg_footer():
    h = 50
    cx = W / 2
    inner = (
        f'<rect x="{GUT}" y="14" width="{cx - 46 - GUT}" height="1" class="h"/>'
        f'<rect x="{cx + 46}" y="14" width="{W - GUT - cx - 46}" height="1" class="h"/>'
        f'<rect x="{cx - 3}" y="11" width="6" height="6" transform="rotate(45 {cx} 14)" '
        f'class="seal"/>'
        f'<text x="{cx}" y="36" text-anchor="middle" font-family="{MONO}" '
        f'font-size="10" letter-spacing="1.5" class="m">'
        f'Crafted with restraint · 手工 SVG · 2026</text>'
    )
    return panel(h, inner)


def data_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# ---------------------------------------------------------------- 主流程

def main():
    d = fetch_all()
    longest, current = calc_streaks(d["days"])
    now = datetime.now(TZ)
    stats = {
        "total": d["cal"]["totalContributions"],
        "stars": sum(r["stargazers_count"] for r in d["repos"]),
        "repos": len([r for r in d["repos"] if not r.get("fork")]),
        "followers": d["user"]["followers"],
        "longest": longest,
        "current": current,
        "updated": now.strftime("%Y-%m-%d %H:%M"),
    }

    parts = {
        "HEADER": svg_header(d),
        "MANIFESTO": svg_manifesto(),
        "STATS": svg_stats(stats),
        "TREND": svg_trend(d),
        "WEEKDAY": svg_weekday(d),
        "YEAR3D": svg_year3d(d),
        "LANGS": svg_langs(d),
        "SKILLS": svg_skills(),
        "REPOS": svg_repos(d),
        "FEED": svg_feed(d),
        "FOOTER": svg_footer(),
        "UPDATED": now.strftime("%Y-%m-%d %H:%M"),
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
    ALT = {"HEADER": "琉璃幻影", "MANIFESTO": "个人宣言", "STATS": "GitHub 数据",
           "TREND": "近 60 天每日贡献", "WEEKDAY": "每周贡献节奏",
           "YEAR3D": "近 13 周贡献等距图", "LANGS": "语言构成", "SKILLS": "工具箱",
           "REPOS": "仓库矩阵", "FEED": "近期投入", "FOOTER": "页脚",
           "UPDATED": "更新时间"}
    for k, v in parts.items():
        if k == "UPDATED":
            tpl = tpl.replace(f"<!--{k}-->", v)
        else:
            tpl = tpl.replace(f"<!--{k}-->",
                              f'<img src="assets/{k.lower()}.svg" alt="{ALT[k]}" />')

    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8") as f:
        f.write(tpl)

    keys = ["HEADER", "MANIFESTO", "STATS", "TREND", "WEEKDAY", "YEAR3D",
            "LANGS", "SKILLS", "REPOS", "FEED", "FOOTER"]

    def column(bg, scheme):
        html = [f"<div style='color-scheme:{scheme};background:{bg};padding:28px 16px;"
                f"display:flex;flex-direction:column;align-items:center'>",
                f"<div style='width:720px;max-width:100%;display:flex;"
                f"flex-direction:column;gap:14px'>"]
        for k in keys:
            html.append(f"<img src='{data_uri(parts[k])}' "
                        f"style='width:100%;display:block'/>")
        html.append("</div></div>")
        return "".join(html)

    prev = ["<!doctype html><meta charset='utf-8'><title>主页预览</title>",
            "<style>body{margin:0;font:12px system-ui}</style><body>",
            column("#0D1117", "dark"), column("#F6F8FA", "light"), "</body>"]
    with open(os.path.join(ROOT, "preview.html"), "w", encoding="utf-8") as f:
        f.write("".join(prev))

    print(f"README 已生成 | 贡献 {stats['total']} · 仓库 {stats['repos']} · "
          f"最长连续 {longest} 天 · 当前连续 {current} 天")


if __name__ == "__main__":
    main()
