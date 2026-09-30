#!/usr/bin/env python3
"""Record Obsidian plugin download counts and redraw the chart and README section."""

import csv
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path

USER = "milad-s5"
PROFILE_URL = f"https://community.obsidian.md/users/{USER}"
PLUGIN_URL = "https://community.obsidian.md/plugins/{slug}"

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "stats" / "downloads.csv"
SVG_PATH = ROOT / "stats" / "downloads-{mode}.svg"
README = ROOT / "README.md"
START, END = "<!-- plugin-stats:start -->", "<!-- plugin-stats:end -->"
FIELDS = ["date", "id", "slug", "name", "downloads"]

# Categorical slots in fixed order; a plugin keeps its slot (by Obsidian id) forever.
THEMES = {
    "light": {
        "surface": "#ffffff", "text": "#1f2328", "muted": "#59636e", "grid": "#e6e6e3",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                   "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    },
    "dark": {
        "surface": "#0d1117", "text": "#f0f6fc", "muted": "#9198a1", "grid": "#262c36",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500",
                   "#d55181", "#008300", "#9085e9", "#e66767"],
    },
}


def fetch_plugins():
    req = urllib.request.Request(PROFILE_URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    # The page is a Next.js app; its data sits in self.__next_f.push([1, "<json string>"]) chunks.
    payload = "".join(
        json.loads(chunk)
        for chunk in re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    )
    at = payload.find('"plugins":[')
    if at < 0:
        raise SystemExit("plugin list not found on profile page")
    plugins, _ = json.JSONDecoder().raw_decode(payload, at + len('"plugins":'))
    return [p for p in plugins if p.get("type") == "plugin"]


def load_rows():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return [{**r, "id": int(r["id"]), "downloads": int(r["downloads"])} for r in csv.DictReader(f)]


def save_rows(rows):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["date"], r["id"])))


def nice_step(span, ticks=5):
    raw = max(span, 1) / ticks
    mag = 10 ** (len(str(int(raw))) - 1)
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def render_svg(rows, mode):
    t = THEMES[mode]
    w, h = 800, 360
    left, right, top, bottom = 56, 24, 64, 40

    series = {}
    for r in rows:
        series.setdefault(r["id"], {"name": r["name"], "points": []})["points"].append(
            (dt.date.fromisoformat(r["date"]), r["downloads"]))
    ids = sorted(series)
    colors = {pid: t["series"][i] for i, pid in enumerate(ids[: len(t["series"])])}

    dates = sorted({d for s in series.values() for d, _ in s["points"]})
    d0, d1 = dates[0], dates[-1]
    days = max((d1 - d0).days, 1)
    step = nice_step(max(r["downloads"] for r in rows))
    ymax = max(step, step * -(-max(r["downloads"] for r in rows) // step))

    x = lambda d: left + (w - left - right) * ((d - d0).days / days if d1 > d0 else 0.5)
    y = lambda v: top + (h - top - bottom) * (1 - v / ymax)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" font-size="12">',
        f'<rect width="{w}" height="{h}" rx="6" fill="{t["surface"]}"/>',
    ]
    # Legend: one row of swatch + name, the latest count carried by the README table.
    lx = left
    for pid, c in colors.items():
        name = series[pid]["name"]
        out.append(f'<rect x="{lx}" y="22" width="10" height="10" rx="2" fill="{c}"/>')
        out.append(f'<text x="{lx + 16}" y="31" fill="{t["text"]}">{name}</text>')
        lx += 16 + len(name) * 6.2 + 20
    v = 0
    while v <= ymax:
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" '
                   f'stroke="{t["grid"]}" stroke-width="1"/>')
        out.append(f'<text x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end" fill="{t["muted"]}">{v:,.0f}</text>')
        v += step

    n = min(len(dates), 6)
    tick_dates = sorted({dates[round(i * (len(dates) - 1) / max(n - 1, 1))] for i in range(n)})
    for d in tick_dates:
        anchor = "middle" if d0 == d1 else "start" if d == d0 else "end" if d == d1 else "middle"
        out.append(f'<text x="{x(d):.1f}" y="{h - bottom + 20}" text-anchor="{anchor}" '
                   f'fill="{t["muted"]}">{d.strftime("%b %-d, %Y" if d == d1 else "%b %-d")}</text>')

    for pid in ids:
        if pid not in colors:
            continue
        pts = sorted(series[pid]["points"])
        c = colors[pid]
        if len(pts) > 1:
            path = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in pts)
            out.append(f'<polyline points="{path}" fill="none" stroke="{c}" stroke-width="2" '
                       f'stroke-linejoin="round" stroke-linecap="round"/>')
        d, v = pts[-1]
        out.append(f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="4" fill="{c}" '
                   f'stroke="{t["surface"]}" stroke-width="2"><title>{series[pid]["name"]}: {v:,}</title></circle>')

    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_readme_section(today, latest):
    total = sum(p["downloads"] for p in latest)
    lines = [
        START,
        "## Obsidian plugins",
        "",
        f"**{total:,}** total downloads across {len(latest)} plugins "
        f"([profile]({PROFILE_URL})) · updated {today}",
        "",
        "<picture>",
        '  <source media="(prefers-color-scheme: dark)" srcset="stats/downloads-dark.svg">',
        '  <img alt="Downloads of each Obsidian plugin over time" src="stats/downloads-light.svg">',
        "</picture>",
        "",
        "| Plugin | Downloads |",
        "|---|--:|",
    ]
    for p in sorted(latest, key=lambda p: -p["downloads"]):
        lines.append(f"| [{p['name']}]({PLUGIN_URL.format(slug=p['slug'])}) | {p['downloads']:,} |")
    lines.append(END)
    return "\n".join(lines)


def main():
    today = dt.date.today().isoformat()
    plugins = fetch_plugins()
    latest = [{"date": today, "id": p["id"], "slug": p["slug"], "name": p["name"],
               "downloads": int(p["downloads"])} for p in plugins]

    rows = [r for r in load_rows() if r["date"] != today] + latest
    save_rows(rows)

    for mode in THEMES:
        SVG_PATH.with_name(SVG_PATH.name.format(mode=mode)).write_text(render_svg(rows, mode), encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    section = render_readme_section(today, latest)
    if START in readme:
        readme = re.sub(re.escape(START) + ".*?" + re.escape(END), lambda _: section, readme, flags=re.S)
    else:
        readme = readme.rstrip("\n") + "\n\n" + section + "\n"
    README.write_text(readme, encoding="utf-8")

    for p in latest:
        print(f"{p['downloads']:>7,}  {p['name']}")


if __name__ == "__main__":
    main()
