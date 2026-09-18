#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""几何自检：扫描 assets/*.svg，找出越界 / 文本左溢出问题。"""
import os
import sys
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK，打不出 ✅
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W = 720
NS = "{http://www.w3.org/2000/svg}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


def text_width(txt, size):
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in txt) * size


problems = 0
for fn in sorted(os.listdir(ASSETS)):
    if not fn.endswith(".svg"):
        continue
    root = ET.fromstring(open(os.path.join(ASSETS, fn), encoding="utf-8").read())
    vb = [float(x) for x in root.get("viewBox").split()]
    w, h = vb[2], vb[3]
    xmin, ymin, xmax, ymax = vb[0], vb[1], vb[0] + vb[2], vb[1] + vb[3]
    name = fn
    max_x = max_y = min_x = 0.0
    for el in root.iter():
        t = el.tag.replace(NS, "")
        try:
            if t == "rect":
                x = float(el.get("x", 0)); y = float(el.get("y", 0))
                max_x = max(max_x, x + float(el.get("width", 0)))
                max_y = max(max_y, y + float(el.get("height", 0)))
            elif t == "circle":
                cx = float(el.get("cx", 0)); cy = float(el.get("cy", 0)); r = float(el.get("r", 0))
                max_x = max(max_x, cx + r); max_y = max(max_y, cy + r)
            elif t == "text":
                x = float(el.get("x", 0)); y = float(el.get("y", 0))
                anchor = el.get("text-anchor", "start")
                size = float(el.get("font-size", 12))
                tw = text_width(el.text or "", size)
                if anchor == "middle":
                    max_x = max(max_x, x + tw / 2); min_x = x - tw / 2
                elif anchor == "end":
                    max_x = max(max_x, x); min_x = x - tw
                else:
                    max_x = max(max_x, x + tw); min_x = x
                max_y = max(max_y, y + size * 0.25)
                if min_x < xmin - 0.5:
                    print(f"  ⚠ [{name}] 文本左溢出 x={min_x:.1f}: {(el.text or '')[:18]}")
                    problems += 1
        except (TypeError, ValueError):
            pass
    flags = []
    if max_x > xmax + 0.5:
        flags.append(f"右越界 {max_x:.1f}>{xmax:.0f}")
    if max_y > ymax + 0.5:
        flags.append(f"下越界 {max_y:.1f}>{ymax:.0f}")
    status = "❌ " + ", ".join(flags) if flags else "✅"
    if flags:
        problems += 1
    print(f"  {status}  [{name}] {w:.0f}x{h:.0f}  边界 x<={max_x:.0f} y<={max_y:.0f}")

print("\n问题数:", problems)
sys.exit(1 if problems else 0)
