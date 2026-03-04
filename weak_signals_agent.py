"""
Weak Signals Agent — "Lovec slabých signálů"
=============================================
Každý týden prohledá arXiv, SSRN, bioRxiv, RSS zdroje think-tanků
a zahraniční akademické zdroje. Claude identifikuje 5 "signálů týdne"
— průniky témat na okraji pozornosti s potenciálem za 5–10 let.

Výstup: Markdown soubor připravený pro GitHub Pages.
"""

import os
import re
import json
import time
import logging
import requests
import anthropic
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ARXIV_QUERIES = [
    "collective behavior emergence complexity social systems",
    "microbiome cognition behavior neuroscience",
    "urban metabolism material flows circular economy",
    "algorithmic governance legitimacy democratic theory",
    "longevity inequality access healthspan",
    "synthetic biology governance biosecurity dual use",
    "climate migration identity cultural transformation",
    "attention economy cognition collective intelligence",
    "post-growth economics wellbeing measurement",
    "indigenous knowledge systems sustainability science",
]

BIORXIV_RSS_FEEDS = [
    "https://www.biorxiv.org/rss/current",
    "https://www.medrxiv.org/rss/current",
]

THINKTANK_RSS_FEEDS = [
    "https://www.swpberlin.org/en/rss/publications",
    "https://www.fiia.fi/en/feed/",
    "https://www.orfonline.org/feed/",
    "https://www.africaportal.org/publications/rss/",
    "https://www.ineteconomics.org/perspectives/blog/rss.xml",
    "https://evonomics.com/feed/",
    "https://datasociety.net/feed/",
    "https://points.datasociety.net/feed",
    "https://www.iftf.org/rss",
    "https://feeds.feedburner.com/InstituteMontaigne",
]

SSRN_SEARCH_TERMS = [
    "weak signals futures",
    "emerging norms governance gap",
    "cross-disciplinary spillover effects",
    "liminal institutions social change",
    "epistemic communities policy fringe",
]

MAX_PAPERS_PER_SOURCE = 8
MAX_TOTAL_ITEMS = 60
OUTPUT_DIR = Path("docs/signals")


def fetch_arxiv(query: str, max_results: int = 5) -> list[dict]:
    url = "http://export.arxiv.org/api/query"
    params = {"search_query": f"all:{query}", "start": 0, "max_results": max_results,
               "sortBy": "submittedDate", "sortOrder": "descending"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            summary = entry.find("atom:summary", ns)
            link = entry.find("atom:id", ns)
            published = entry.find("atom:published", ns)
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
            if title is not None:
                items.append({
                    "source": "arXiv",
                    "title": title.text.strip().replace("\n", " "),
                    "summary": (summary.text or "")[:500].strip(),
                    "url": link.text.strip() if link is not None else "",
                    "published": published.text[:10] if published is not None else "",
                    "authors": authors[:3],
                    "query": query,
                })
        return items
    except Exception as e:
        log.warning(f"arXiv fetch failed for '{query}': {e}")
        return []


def fetch_rss(url: str, max_items: int = 5) -> list[dict]:
    try:
        feed = feedparser.parse(url)
        items = []
        domain = re.sub(r"https?://(www\.)?", "", url).split("/")[0]
        for entry in feed.entries[:max_items]:
            summary = getattr(entry, "summary", "") or ""
            summary = re.sub(r"<[^>]+>", "", summary)[:500]
            items.append({
                "source": domain,
                "title": getattr(entry, "title", ""),
                "summary": summary.strip(),
                "url": getattr(entry, "link", ""),
                "published": getattr(entry, "published", "")[:10],
                "authors": [],
                "query": "rss",
            })
        return items
    except Exception as e:
        log.warning(f"RSS fetch failed for '{url}': {e}")
        return []


def fetch_ssrn(query: str, max_results: int = 4) -> list[dict]:
    url = "https://api.ssrn.com/content/v1/bindings"
    params = {"query": query, "count": max_results, "sort": "date"}
    headers = {"User-Agent": "WeakSignalsBot/1.0 (research aggregator)"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        items = []
        for paper in data.get("papers", []):
            items.append({
                "source": "SSRN",
                "title": paper.get("title", ""),
                "summary": paper.get("abstract", "")[:500],
                "url": f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={paper.get('id','')}",
                "published": paper.get("date", "")[:10],
                "authors": [a.get("name", "") for a in paper.get("authors", [])[:3]],
                "query": query,
            })
        return items
    except Exception as e:
        log.warning(f"SSRN fetch failed for '{query}': {e}")
        return []


def collect_all_items() -> list[dict]:
    all_items = []
    log.info("📡 Stahuji arXiv preprinty...")
    for query in ARXIV_QUERIES:
        items = fetch_arxiv(query, max_results=MAX_PAPERS_PER_SOURCE)
        all_items.extend(items)
        time.sleep(1)
    log.info("🧬 Stahuji bioRxiv/medRxiv RSS...")
    for feed_url in BIORXIV_RSS_FEEDS:
        items = fetch_rss(feed_url, max_items=MAX_PAPERS_PER_SOURCE)
        all_items.extend(items)
    log.info("🌍 Stahuji think-tank RSS zdroje...")
    for feed_url in THINKTANK_RSS_FEEDS:
        items = fetch_rss(feed_url, max_items=4)
        all_items.extend(items)
    log.info("📚 Stahuji SSRN...")
    for term in SSRN_SEARCH_TERMS:
        items = fetch_ssrn(term, max_results=4)
        all_items.extend(items)
        time.sleep(0.5)
    seen_urls = set()
    unique_items = []
    for item in all_items:
        if item["url"] not in seen_urls and item["title"]:
            seen_urls.add(item["url"])
            unique_items.append(item)
    log.info(f"✅ Celkem unikátních položek: {len(unique_items)}")
    return unique_items[:MAX_TOTAL_ITEMS]


SYSTEM_PROMPT = """Jsi expert na futures studies, komplexní systémy a interdisciplinární výzkum.
Tvůj úkol: identifikovat "slabé signály" — jevy na okraji pozornosti, které mohou být klíčové za 5–10 let.

PRAVIDLA:
- Hledej PRŮNIKY mezi obory, ne izolované trendy
- Preferuj jevy, které HLAVNÍ MÉDIA ZATÍM IGNORUJÍ
- Každý signál musí mít KONKRÉTNÍ mechanismus, proč by mohl být důležitý
- Vyhýbej se hype tématům (AI, klimatická krize obecně — pokud nenajdeš skutečně okrajový úhel)
- Piš česky, odborně ale srozumitelně
- Výstup musí být validní JSON — nic jiného"""

ANALYSIS_PROMPT_TEMPLATE = """Analyzuj tyto vědecké práce a zdroje ze tohoto týdne:

{items_json}

Vyber 5 nejzajímavějších "slabých signálů" — jevů na okraji pozornosti s potenciálem stát se důležitými za 5–10 let.

Vrať POUZE validní JSON v tomto formátu:
{{
  "signals": [
    {{
      "title": "Krátký název signálu (max 8 slov)",
      "disciplines": ["obor1", "obor2"],
      "why_peripheral": "Proč to zatím nikdo moc nesleduje (1–2 věty)",
      "mechanism": "Konkrétní mechanismus, jak by to mohlo být důležité (2–3 věty)",
      "horizon": "Za jak dlouho a za jakých podmínek (1–2 věty)",
      "source_titles": ["název práce 1", "název práce 2"],
      "wildcard_question": "Provokativní otázka k zamyšlení pro posluchače podcastu"
    }}
  ],
  "meta_pattern": "Jeden souhrnný meta-vzorec, který spojuje více signálů tohoto týdne (2–3 věty)"
}}"""


def analyze_with_claude(items: list[dict]) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    items_summary = []
    for item in items:
        items_summary.append({
            "source": item["source"],
            "title": item["title"],
            "summary": item["summary"][:300],
            "published": item["published"],
        })
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        items_json=json.dumps(items_summary, ensure_ascii=False, indent=2)
    )
    log.info("🧠 Analyzuji s Claude...")
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error: {e}\nRaw: {raw[:300]}")
        raise


def generate_markdown(analysis: dict, items: list[dict], week_str: str) -> str:
    signals = analysis.get("signals", [])
    meta_pattern = analysis.get("meta_pattern", "")
    date_generated = datetime.now().strftime("%d. %m. %Y")
    week_num = datetime.now().isocalendar()[1]
    year = datetime.now().year
    signal_emojis = ["🔭", "🧬", "⚡", "🌀", "🔮"]
    lines = [
        "---", "layout: post",
        f'title: "Slabé signály — týden {week_num}/{year}"',
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "category: signals", "---", "",
        f"# 🔍 Slabé signály týdne {week_num}/{year}", "",
        f"*Vygenerováno: {date_generated} | Zdrojů prohledáno: {len(items)} | Agent: Weak Signals v1*",
        "", "---", "",
    ]
    if meta_pattern:
        lines += ["## 🧩 Meta-vzorec tohoto týdne", "", f"> {meta_pattern}", "", "---", ""]
    lines += ["## 5 signálů týdne", ""]
    for i, signal in enumerate(signals):
        emoji = signal_emojis[i] if i < len(signal_emojis) else "📡"
        disciplines = " · ".join(signal.get("disciplines", []))
        lines += [
            f"### {emoji} Signál {i+1}: {signal.get('title', '')}",
            "", f"**Disciplíny:** {disciplines}", "",
            "**Proč to zatím nikdo nesleduje:**  ", f"{signal.get('why_peripheral', '')}",
            "", "**Mechanismus:**  ", f"{signal.get('mechanism', '')}",
            "", "**Horizont:**  ", f"{signal.get('horizon', '')}", "",
        ]
        sources = signal.get("source_titles", [])
        if sources:
            lines.append("**Zdrojové práce:**")
            for src in sources:
                lines.append(f"- _{src}_")
            lines.append("")
        wildcard = signal.get("wildcard_question", "")
        if wildcard:
            lines += ["**❓ Wildcard pro podcast:**", f"> {wildcard}", ""]
        lines += ["---", ""]
    source_counts: dict[str, int] = {}
    for item in items:
        source_counts[item["source"]] = source_counts.get(item["source"], 0) + 1
    lines += ["## 📚 Prohledané zdroje tento týden", ""]
    for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{source}**: {count} položek")
    lines += ["", "---", "",
        "*Tento report je surový materiál pro podcast. Interpretace a narativ jsou na tobě.*", "",
        f"*Agent prohledal: arXiv, bioRxiv, medRxiv, SSRN a {len(THINKTANK_RSS_FEEDS)} think-tank RSS feedů.*",
    ]
    return "\n".join(lines)


def update_index(output_dir: Path) -> None:
    posts = sorted(output_dir.glob("*.md"), reverse=True)
    if not posts:
        return
    lines = ["---", "layout: default", "title: Slabé signály — archiv", "---", "",
             "# 🔍 Archiv slabých signálů", "", "| Vydání | Datum |", "|--------|-------|"]
    for post in posts:
        if post.name == "index.md":
            continue
        name = post.stem
        parts = name.split("-")
        if len(parts) >= 3:
            label = f"Týden {parts[2]}/{parts[1]}"
            date_str = f"{parts[1]}-W{parts[2]}"
        else:
            label = name
            date_str = ""
        lines.append(f"| [{label}]({name}.html) | {date_str} |")
    (output_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    log.info("🚀 Spouštím Weak Signals Agent...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    week_num = now.isocalendar()[1]
    year = now.year
    week_str = f"{year}-W{week_num:02d}"
    output_file = OUTPUT_DIR / f"signals-{year}-{week_num:02d}.md"
    items = collect_all_items()
    if not items:
        log.error("❌ Žádné položky nebyly staženy.")
        return
    analysis = analyze_with_claude(items)
    markdown = generate_markdown(analysis, items, week_str)
    output_file.write_text(markdown, encoding="utf-8")
    log.info(f"✅ Signály uloženy: {output_file}")
    update_index(OUTPUT_DIR)
    for i, signal in enumerate(analysis.get("signals", []), 1):
        log.info(f"  Signal {i}: {signal.get('title', '')}")
    log.info("🎉 Hotovo!")


if __name__ == "__main__":
    main()
