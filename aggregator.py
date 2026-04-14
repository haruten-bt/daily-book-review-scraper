#!/usr/bin/env python3
"""
Stage2: 個別記事MDから週まとめMDを生成するスクリプト
"""

import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ARTICLES_DIR = Path(__file__).parent / "articles"
WEEKLY_DIR = Path(__file__).parent / "weekly"

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def parse_article_meta(file_path: Path) -> dict | None:
    """
    MDファイルのフロントマター部分からメタ情報を読み取る。
    Returns dict with keys: title, pub_date, url, book, body
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"  [警告] 読み込み失敗 {file_path}: {e}")
        return None

    lines = content.splitlines()
    if not lines:
        return None

    # 1行目: # タイトル
    title = lines[0].lstrip("# ").strip() if lines[0].startswith("#") else "タイトル不明"

    pub_date = None
    url = None
    book = None
    body_start = 0

    for i, line in enumerate(lines):
        m = re.match(r"-\s+\*\*公開日\*\*:\s*(.+)", line)
        if m:
            pub_date = m.group(1).strip()
        m = re.match(r"-\s+\*\*URL\*\*:\s*(.+)", line)
        if m:
            url = m.group(1).strip()
        m = re.match(r"-\s+\*\*書籍\*\*:\s*(.+)", line)
        if m:
            book = m.group(1).strip()
        if line.strip() == "---" and i > 3:
            body_start = i + 1
            break

    if pub_date is None:
        return None

    body = "\n".join(lines[body_start:]).strip()

    return {
        "title": title,
        "pub_date": pub_date,
        "url": url or "",
        "book": book or "不明",
        "body": body,
        "file_path": file_path,
    }


def get_week_info(pub_date_str: str) -> tuple[int, int, int, date, date]:
    """
    公開日から (year, month, week_num, week_start, week_end) を返す。
    week_num: その月の第N週（月曜始まり）
    week_start/week_end: 週の月曜〜日曜
    月は記事の公開日に基づく。
    """
    d = date.fromisoformat(pub_date_str)
    # 週の月曜日
    week_start = d - timedelta(days=d.weekday())
    week_end = week_start + timedelta(days=6)

    # その月の第N週を計算（月の1日が何曜日かに基づく）
    first_day = date(d.year, d.month, 1)
    first_monday = first_day + timedelta(days=(7 - first_day.weekday()) % 7)
    if d < first_monday:
        # 月の最初の月曜より前 → 第1週扱い
        week_num = 1
        week_start = first_day - timedelta(days=first_day.weekday())
    else:
        week_num = ((d - first_monday).days // 7) + 2

    return d.year, d.month, week_num, week_start, week_end


def week_filename(year: int, month: int, week_num: int,
                  week_start: date, week_end: date) -> str:
    """週ファイル名を生成する。例: 2026年_04月_第3週（0413-0417）.md"""
    start_str = week_start.strftime("%m%d")
    end_str = week_end.strftime("%m%d")
    return f"{year}年_{month:02d}月_第{week_num}週（{start_str}-{end_str}）.md"


def week_heading(year: int, month: int, week_num: int,
                 week_start: date, week_end: date) -> str:
    """週見出しを生成する。例: 毎日書評 2026年04月 第3週（04/13〜04/17）"""
    start_str = week_start.strftime("%m/%d")
    end_str = week_end.strftime("%m/%d")
    return f"# 毎日書評 {year}年{month:02d}月 第{week_num}週（{start_str}〜{end_str}）"


def build_weekly_markdown(heading: str,
                          day_articles: dict[date, list[dict]]) -> str:
    """週まとめMarkdownを生成する。"""
    lines = [heading, ""]

    for day in sorted(day_articles.keys()):
        weekday = WEEKDAY_JA[day.weekday()]
        lines.append(f"## {day.isoformat()}（{weekday}）")

        for art in day_articles[day]:
            lines.append(f"### {art['title']}")
            lines.append(f"- **書籍**: {art['book']}")
            lines.append(f"- **URL**: {art['url']}")
            lines.append("")
            lines.append(art["body"])
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def run() -> None:
    print("[開始] 週まとめ生成")

    # 全記事ファイルを収集
    article_files = sorted(ARTICLES_DIR.rglob("*.md"))
    print(f"[記事] {len(article_files)}件のMDファイルを発見")

    # week_key → {date: [article, ...]} のマッピング
    # week_key = (year, month, week_num, week_start, week_end)
    weeks: dict[tuple, dict[date, list[dict]]] = defaultdict(lambda: defaultdict(list))

    skipped = 0
    for fp in article_files:
        meta = parse_article_meta(fp)
        if meta is None:
            skipped += 1
            continue

        try:
            year, month, week_num, week_start, week_end = get_week_info(meta["pub_date"])
        except (ValueError, TypeError) as e:
            print(f"  [警告] 日付パース失敗 {fp.name}: {e}")
            skipped += 1
            continue

        pub_day = date.fromisoformat(meta["pub_date"])
        week_key = (year, month, week_num, week_start, week_end)
        weeks[week_key][pub_day].append(meta)

    print(f"[週] {len(weeks)}週分のデータを生成")
    if skipped:
        print(f"[スキップ] {skipped}件")

    generated = 0
    for (year, month, week_num, week_start, week_end), day_articles in weeks.items():
        heading = week_heading(year, month, week_num, week_start, week_end)
        content = build_weekly_markdown(heading, day_articles)

        dir_path = WEEKLY_DIR / str(year) / f"{month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)

        filename = week_filename(year, month, week_num, week_start, week_end)
        file_path = dir_path / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        article_count = sum(len(v) for v in day_articles.values())
        print(f"  [保存] {file_path.relative_to(Path(__file__).parent)} ({article_count}記事)")
        generated += 1

    print(f"\n[完了] {generated}件の週まとめファイルを生成しました")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
