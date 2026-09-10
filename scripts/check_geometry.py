#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""几何自检：扫描 README 里的内联 SVG，找出越界 / 重叠问题。"""
import os
import re
import sys
import xml.etree.ElementTree as ET

W = 800
NS = "{http://www.w3.org/2000/svg}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
    md = f.read()

svgs = re.findall(r"<svg.*?</svg>", md, re.S)
print(f"内联 SVG 数量: {len(svgs)}")

problems = 0
for idx, s in enumerate(svgs):
    root = ET.fromstring(s)
    vb = [float(x) for x in root.get("viewBox").split()]
    w, h = vb[2], vb[3]
    tag = re.search(r"<text[^>]*>([^<]{2,20})</text>", s)
    name = tag.group(1)[:14] if tag else f"#{idx}"

    max_x, max_y = 0.0, 0.0
    for el in root.iter():
        t = el.tag.replace(NS, "")
        try:
            if t == "rect":
                x = float(el.get("x", 0)); y = float(el.get("y", 0))
                ew = float(el.get("width", 0)); eh = float(el.get("height", 0))
                max_x = max(max_x, x + ew); max_y = max(max_y, y + eh)
            elif t == "circle":
                cx = float(el.get("cx", 0)); cy = float(el.get("cy", 0))
                r = float(el.get("r", 0))
                max_x = max(max_x, cx + r); max_y = max(max_y, cy + r)
            elif t == "text":
                x = float(el.get("x", 0)); y = float(el.get("y", 0))
                anchor = el.get("text-anchor", "start")
                size = float(el.get("font-size", 12))
                txt = el.text or ""
                # 粗略宽度：中文按 1.0em，ASCII 按 0.55em
                tw = sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in txt) * size
                if anchor == "middle":
                    max_x = max(max_x, x + tw / 2); min_x = x - tw / 2
                elif anchor == "end":
                    max_x = max(max_x, x); min_x = x - tw
                else:
                    max_x = max(max_x, x + tw); min_x = x
                max_y = max(max_y, y + size * 0.25)
                if min_x < -1:
                    print(f"  ⚠ [{name}] 文本左溢出 x={min_x:.1f}: {txt[:18]}")
                    problems += 1
        except (TypeError, ValueError):
            pass

    flags = []
    if max_x > W + 0.5:
        flags.append(f"右越界 {max_x:.1f}>{W}")
    if max_y > h + 0.5:
        flags.append(f"下越界 {max_y:.1f}>{h:.0f}")
    if flags:
        problems += 1
    status = "❌ " + ", ".join(flags) if flags else "✅"
    print(f"  {status}  [{name}] {w:.0f}x{h:.0f}  内容边界 x<={max_x:.0f} y<={max_y:.0f}")

print("\n问题数:", problems)
sys.exit(1 if problems else 0)
