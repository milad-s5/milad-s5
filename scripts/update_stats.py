#!/usr/bin/env python3
"""Record Obsidian plugin download counts and redraw the chart and README section."""

import csv
import datetime as dt
import html
import json
import math
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

# Up to this many days of history the chart has one bar per day; past it, one bar per week.
DAILY_DAYS = 14
WEEKS = 12

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


def gains(rows):
    """{plugin id: {date: downloads gained since that plugin's previous snapshot}}."""
    last, out = {}, {}
    for r in sorted(rows, key=lambda r: (r["date"], r["id"])):
        if r["id"] in last:
            out.setdefault(r["id"], {})[dt.date.fromisoformat(r["date"])] = r["downloads"] - last[r["id"]]
        last[r["id"]] = r["downloads"]
    return out


def gained_since(by_date, end, days=7):
    return sum(v for d, v in by_date.items() if (end - d).days < days)


def buckets(d0, d1):
    """(unit, bar start dates, date -> bar start): days for a short history, else weeks from Monday."""
    if (d1 - d0).days <= DAILY_DAYS:
        return "day", [d0 + dt.timedelta(i) for i in range(1, (d1 - d0).days + 1)], lambda d: d
    monday = lambda d: d - dt.timedelta(d.weekday())
    starts = [monday(d1) - dt.timedelta(weeks=i) for i in reversed(range(WEEKS))]
    return "week", [s for s in starts if s >= monday(d0)], monday


def draw_panel(out, t, x0, y0, pw, ph, name, total, week, starts, stacks):
    """A card: name, total, 7-day gain, and one bar per bucket stacked from (value, color) parts."""
    out.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" rx="6" fill="none" stroke="{t["grid"]}"/>')
    out.append(f'<text x="{x0 + 14}" y="{y0 + 24}" font-weight="600" fill="{t["text"]}">{html.escape(name)}</text>')
    out.append(f'<text x="{x0 + 14}" y="{y0 + 52}" font-size="22" font-weight="600" '
               f'fill="{t["text"]}">{total:,}</text>')
    out.append(f'<text x="{x0 + 22 + len(f"{total:,}") * 13}" y="{y0 + 52}" font-weight="600" '
               f'fill="{t["muted"]}">{week:+,} in 7 days</text>')

    bx0, bx1, by0, by1 = x0 + 14, x0 + pw - 14, y0 + 82, y0 + ph - 28
    out.append(f'<line x1="{bx0}" x2="{bx1}" y1="{by1}" y2="{by1}" stroke="{t["grid"]}"/>')
    if not starts:
        return
    top = max(max(sum(v for v, _ in s) for s in stacks), 1)
    slot = (bx1 - bx0) / len(starts)
    bw = min(slot * 0.6, 48)
    every = math.ceil(len(starts) / max(int((bx1 - bx0) // 56), 1))  # date labels need ~56px each
    for i, (d, stack) in enumerate(zip(starts, stacks)):
        cx, y = bx0 + slot * (i + 0.5), by1
        for v, c in stack:
            if v > 0:
                bh = (by1 - by0) * v / top
                y -= bh
                out.append(f'<rect x="{cx - bw / 2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{c}"/>')
        if slot >= 22:
            out.append(f'<text x="{cx:.1f}" y="{y - 5:.1f}" text-anchor="middle" '
                       f'fill="{t["muted"]}">{sum(v for v, _ in stack):,}</text>')
        if (len(starts) - 1 - i) % every == 0:
            out.append(f'<text x="{cx:.1f}" y="{by1 + 16}" text-anchor="middle" '
                       f'fill="{t["muted"]}">{d.strftime("%b %-d")}</text>')


def render_svg(rows, mode):
    t = THEMES[mode]
    w, pad, gap = 800, 16, 16
    pw, ph, total_h = (w - 2 * pad - gap) // 2, 176, 200

    d0 = dt.date.fromisoformat(min(r["date"] for r in rows))
    d1 = dt.date.fromisoformat(max(r["date"] for r in rows))
    latest = sorted((r for r in rows if r["date"] == d1.isoformat()), key=lambda r: -r["downloads"])
    slots = sorted({r["id"] for r in rows})
    colors = {pid: t["series"][i % len(t["series"])] for i, pid in enumerate(slots)}
    gained = gains(rows)
    unit, starts, bucket_of = buckets(d0, d1)

    per_bar = {}
    for p in latest:
        sums = dict.fromkeys(starts, 0)
        for d, v in gained.get(p["id"], {}).items():
            if bucket_of(d) in sums:
                sums[bucket_of(d)] += v
        per_bar[p["id"]] = [sums[s] for s in starts]

    rows_of_cards = math.ceil(len(latest) / 2)
    h = 48 + total_h + gap + rows_of_cards * (ph + gap)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" font-size="12">',
        f'<rect width="{w}" height="{h}" rx="6" fill="{t["surface"]}"/>',
        f'<text x="{pad}" y="30" font-size="15" font-weight="600" fill="{t["text"]}">New downloads per {unit}</text>',
        f'<text x="{w - pad}" y="30" text-anchor="end" fill="{t["muted"]}">each card has its own scale</text>',
    ]

    # All plugins: bars stacked in card order, so each segment matches its card's color.
    draw_panel(out, t, pad, 48, w - 2 * pad, total_h, "All plugins",
               sum(p["downloads"] for p in latest),
               sum(gained_since(gained.get(p["id"], {}), d1) for p in latest), starts,
               [[(per_bar[p["id"]][i], colors[p["id"]]) for p in latest] for i in range(len(starts))])

    for k, p in enumerate(latest):
        draw_panel(out, t, pad + (k % 2) * (pw + gap), 48 + total_h + gap + (k // 2) * (ph + gap), pw, ph,
                   p["name"], p["downloads"], gained_since(gained.get(p["id"], {}), d1), starts,
                   [[(v, colors[p["id"]])] for v in per_bar[p["id"]]])

    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_readme_section(today, latest, rows):
    total = sum(p["downloads"] for p in latest)
    end = dt.date.fromisoformat(today)
    gained = gains(rows)
    week = {p["id"]: gained_since(gained.get(p["id"], {}), end) for p in latest}
    lines = [
        START,
        "## Obsidian plugins",
        "",
        f"**{total:,}** total downloads across {len(latest)} plugins "
        f"([profile]({PROFILE_URL})) · updated {today}",
        "",
        "<picture>",
        '  <source media="(prefers-color-scheme: dark)" srcset="stats/downloads-dark.svg">',
        '  <img alt="New downloads of each Obsidian plugin over time" src="stats/downloads-light.svg">',
        "</picture>",
        "",
        "| Plugin | Downloads | Last 7 days |",
        "|---|--:|--:|",
    ]
    for p in sorted(latest, key=lambda p: -p["downloads"]):
        lines.append(f"| [{p['name']}]({PLUGIN_URL.format(slug=p['slug'])}) "
                     f"| {p['downloads']:,} | {week[p['id']]:+,} |")
    lines.append(f"| **Total** | **{total:,}** | **{sum(week.values()):+,}** |")
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
    section = render_readme_section(today, latest, rows)
    if START in readme:
        readme = re.sub(re.escape(START) + ".*?" + re.escape(END), lambda _: section, readme, flags=re.S)
    else:
        readme = readme.rstrip("\n") + "\n\n" + section + "\n"
    README.write_text(readme, encoding="utf-8")

    for p in latest:
        print(f"{p['downloads']:>7,}  {p['name']}")


if __name__ == "__main__":
    main()
