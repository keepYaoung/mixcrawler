#!/usr/bin/env python3
"""
Analyze a mixcrawler JSONL dump and emit a Markdown report.

Usage:
    python3 analyze.py                       # newest output/*.jsonl
    python3 analyze.py output/crawl_X.jsonl  # a specific dump
    python3 analyze.py --out report.md

Report covers: volume, date range, PTE task-module mentions, tools/resources,
weekly trend, and the top-scored advice (posts + comments) quoted verbatim.
"""
import argparse, glob, json, os, re, sys, collections
from datetime import datetime

# PTE speaking/writing/reading/listening task modules and their common aliases.
PTE_MODULES = {
    "Read Aloud":            [r"\bread aloud\b", r"\bRA\b"],
    "Repeat Sentence":       [r"\brepeat sentence\b", r"\bRS\b"],
    "Describe Image":        [r"\bdescribe image\b", r"\bDI\b"],
    "Retell Lecture":        [r"\bretell lecture\b", r"\bRTL\b", r"\bRL\b"],
    "Answer Short Question": [r"\bASQ\b", r"\bshort question\b"],
    "Summarize Written Text":[r"\bsummari[sz]e written text\b", r"\bSWT\b"],
    "Write Essay":           [r"\bwrite essay\b", r"\bessay\b", r"\bWE\b"],
    "Reading FIB":           [r"\bRFIB\b", r"\bR&W FIB\b", r"\bfill in the blank", r"\bFIB\b"],
    "Reorder Paragraph":     [r"\breorder\b", r"\bRO\b"],
    "Summarize Spoken Text": [r"\bSST\b", r"\bsummari[sz]e spoken\b"],
    "Write from Dictation":  [r"\bWFD\b", r"\bdictation\b"],
    "Highlight Correct Summary": [r"\bHCS\b", r"\bhighlight correct summary\b"],
    "Retell / Fluency":      [r"\bfluency\b", r"\bpronunciation\b"],
}

TOOLS = {
    "APEUni":      [r"\bapeuni\b", r"\bape uni\b"],
    "Pearson/PTE official": [r"\bpearson\b", r"\bpte academic\b", r"\bofficial\b"],
    "PTE Core":    [r"\bpte core\b"],
    "Templates":   [r"\btemplate", ],
    "Rescore":     [r"\brescor", r"\bre-?mark\b", r"\brecheck\b"],
    "AI scoring":  [r"\bai\b.*scor", r"\bscoring\b"],
    "Mock tests":  [r"\bmock\b", r"\bpractice test\b", r"\bscored test\b"],
}

SCORE_TARGETS = ["79", "90", "65", "58", "50"]


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def count_patterns(rows, mapping):
    counts = collections.Counter()
    for label, pats in mapping.items():
        rx = re.compile("|".join(pats), re.I)
        counts[label] = sum(1 for r in rows if rx.search(f"{r.get('title','')} {r.get('text','')}"))
    return counts


def weekly(rows):
    wk = collections.Counter()
    for r in rows:
        d = r.get("created_utc", "")[:10]
        if len(d) == 10:
            try:
                iso = datetime.strptime(d, "%Y-%m-%d").isocalendar()
                wk[f"{iso.year}-W{iso.week:02d}"] += 1
            except ValueError:
                pass
    return dict(sorted(wk.items()))


def top_by_score(rows, n=8, min_len=40):
    scored = [r for r in rows if isinstance(r.get("score"), int) and len(r.get("text", "") or r.get("title", "")) >= min_len]
    return sorted(scored, key=lambda r: r["score"], reverse=True)[:n]


def md_escape(s):
    return (s or "").replace("\n", " ").replace("|", "/").strip()


def blockquote(text, cap=3500):
    """Render body text as a markdown blockquote, preserving paragraphs."""
    text = (text or "").strip()
    truncated = len(text) > cap
    if truncated:
        text = text[:cap].rsplit(" ", 1)[0] + " …"
    lines = [ln.rstrip() for ln in text.split("\n")]
    out = "\n".join(f"> {ln}" if ln else ">" for ln in lines)
    if truncated:
        out += "\n>\n> _(본문 일부 — 전문은 위 링크)_"
    return out


def stamp_from_path(path):
    """crawl_YYYYMMDD_HHMMSS.jsonl -> 'YYMMDD-HHMM'; fallback to now."""
    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})", os.path.basename(path))
    if m:
        y, mo, d, hh, mm = m.groups()
        return f"{y[2:]}{mo}{d}-{hh}{mm}"
    return datetime.now().strftime("%y%m%d-%H%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--out", default=None, help="explicit output path (overrides folder/name)")
    ap.add_argument("--title", default="PTE_경향리포트", help="report title used in filename")
    a = ap.parse_args()

    path = a.path
    if not path:
        files = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "*.jsonl")))
        if not files:
            sys.exit("No output/*.jsonl found. Run crawler.py first.")
        path = files[-1]

    rows = load(path)
    posts = [r for r in rows if r["source"] == "reddit"]
    coms = [r for r in rows if r["source"] == "reddit_comment"]
    reddit = posts + coms
    news = [r for r in rows if r["source"] == "googlenews"]

    dates = sorted(r["created_utc"][:10] for r in rows if r.get("created_utc"))
    span = (dates[0], dates[-1]) if dates else ("?", "?")

    modules = count_patterns(reddit, PTE_MODULES)
    tools = count_patterns(reddit, TOOLS)
    targets = collections.Counter()
    for t in SCORE_TARGETS:
        rx = re.compile(rf"\b{t}\b")
        targets[t] = sum(1 for r in reddit if rx.search(f"{r.get('title','')} {r.get('text','')}"))
    wk = weekly(reddit)

    L = []
    P = L.append
    P(f"# PTE 최근 90일 경향 리포트 (r/PTE)\n")
    P(f"- 데이터: `{os.path.basename(path)}`")
    P(f"- 수집 범위: **{span[0]} ~ {span[1]}**")
    P(f"- 총 {len(rows):,}건 — 레딧 글 {len(posts):,} · 댓글 {len(coms):,} · 뉴스 {len(news):,}\n")

    P("## 1. 가장 많이 언급된 시험 유형 (task module)\n")
    P("| 유형 | 언급 수 |")
    P("|------|--------|")
    for label, c in modules.most_common():
        if c:
            P(f"| {label} | {c} |")
    P("")

    P("## 2. 목표 점수 언급 빈도\n")
    P("| 점수 | 언급 수 |")
    P("|------|--------|")
    for t, c in targets.most_common():
        P(f"| {t} | {c} |")
    P("")

    P("## 3. 자주 등장하는 도구/전략\n")
    P("| 도구/전략 | 언급 수 |")
    P("|-----------|--------|")
    for label, c in tools.most_common():
        if c:
            P(f"| {label} | {c} |")
    P("")

    P("## 4. 주차별 활동량 (레딧 글+댓글)\n")
    P("| 주 | 건수 |")
    P("|----|------|")
    for w, c in wk.items():
        P(f"| {w} | {c} |")
    P("")

    # ---- 5. Full-text advice / experience posts (the goldmine) ----
    P("## 5. 고득점 후기·상세 팁 글 (본문 전문)\n")
    P("_추천수(score) 순. 본문이 있는 후기/팁 글만. 긴 글은 발췌 후 원문 링크._\n")
    rich_posts = [p for p in posts
                  if isinstance(p.get("score"), int) and len((p.get("text") or "")) >= 400]
    rich_posts.sort(key=lambda p: p["score"], reverse=True)
    for p in rich_posts[:12]:
        P(f"### [+{p['score']}] {md_escape(p['title'])[:200]}")
        P(f"<{p['url']}>\n")
        P(blockquote(p.get("text", ""), cap=3500))
        P("")

    # ---- 6. Long advice comments ----
    P("## 6. 조언 댓글 (긴 발췌)\n")
    P("_추천수 순. 80자 이상 실질 조언만(단순 축하 댓글 제외)._\n")
    adv_coms = [c for c in coms
                if isinstance(c.get("score"), int) and len((c.get("text") or "")) >= 80]
    adv_coms.sort(key=lambda c: c["score"], reverse=True)
    for c in adv_coms[:20]:
        P(f"- **[+{c['score']}]** {md_escape(c['text'])[:900]}  \n  <{c['url']}>")
    P("")

    # ---- 7. Short success-story posts (titles only, for breadth) ----
    P("## 7. 그 밖의 후기 글 (제목)\n")
    thin = [p for p in posts if isinstance(p.get("score"), int) and len((p.get("text") or "")) < 400]
    thin.sort(key=lambda p: p["score"], reverse=True)
    for p in thin[:12]:
        P(f"- **[+{p['score']}]** {md_escape(p['title'])[:160]}  \n  <{p['url']}>")
    P("")

    report = "\n".join(L)
    if a.out:
        out = os.path.abspath(a.out)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        reports_dir = os.path.join(here, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        fname = f"{stamp_from_path(path)}-{a.title}.md"
        out = os.path.join(reports_dir, fname)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[saved] {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
