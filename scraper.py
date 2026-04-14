#!/usr/bin/env python3
"""
Stage1: ライフハッカー・ジャパン「印南敦史の毎日書評」記事収集スクリプト
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

BASE_URL = "https://www.lifehacker.jp"
INDEX_URL = "https://www.lifehacker.jp/regular/regular_book_to_read/"
STATE_FILE = Path(__file__).parent / "state.json"
ARTICLES_DIR = Path(__file__).parent / "articles"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"collected_urls": [], "last_run": None}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def sanitize_filename(title: str, max_len: int = 50) -> str:
    """ファイル名に使えない文字をアンダースコアに置換し、長さを制限する。"""
    sanitized = re.sub(r'[/\\:*?"<>|]', "_", title)
    sanitized = sanitized.strip()
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len]
    return sanitized


def get_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as e:
            print(f"  [警告] {url} の取得失敗 (試行{attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def collect_article_urls_from_page(soup: BeautifulSoup) -> list[str]:
    """インデックスページから記事URLを収集する。"""
    urls = []
    for a_tag in soup.select("a[href]"):
        href = a_tag["href"]
        # 記事URLのパターン: /article/YYYY??-book_to_read-NNNN/
        if re.search(r"/article/\d{4,}-book_to_read-\d+/", href):
            full_url = href if href.startswith("http") else BASE_URL + href
            if full_url not in urls:
                urls.append(full_url)
    return urls


def scrape_article(url: str) -> dict | None:
    """記事ページから情報をスクレイプする。"""
    soup = get_page(url)
    if soup is None:
        return None

    # タイトル
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "タイトル不明"

    # 公開日
    pub_date = None
    date_candidates = [
        soup.find("time"),
        soup.find(class_=re.compile(r"date|time|published", re.I)),
        soup.find(attrs={"datetime": True}),
    ]
    for candidate in date_candidates:
        if candidate is None:
            continue
        dt_str = candidate.get("datetime") or candidate.get_text(strip=True)
        if dt_str:
            try:
                pub_date = dateutil_parser.parse(dt_str).strftime("%Y-%m-%d")
                break
            except (ValueError, OverflowError):
                continue

    if pub_date is None:
        # URLから日付を推定 (例: /article/2604-book_to_read-1913/ → 2026-04)
        m = re.search(r"/article/(\d{2})(\d{2})-book_to_read-", url)
        if m:
            pub_date = f"20{m.group(1)}-{m.group(2)}-01"
        else:
            pub_date = datetime.now(JST).strftime("%Y-%m-%d")

    # 本文取得
    body_text = _extract_body(soup)

    # 書籍情報
    book_info = _extract_book_info(soup, body_text)

    return {
        "title": title,
        "pub_date": pub_date,
        "url": url,
        "book": book_info,
        "body": body_text,
    }


def _extract_body(soup: BeautifulSoup) -> str:
    """本文テキストを抽出する。"""
    # 記事本文の候補セレクター（優先順）
    selectors = [
        "article",
        ".article-body",
        ".entry-content",
        ".post-content",
        "#article-body",
        ".body",
        "main",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            # スクリプト・スタイル・ナビ要素を除去
            for tag in el.find_all(["script", "style", "nav", "header", "footer",
                                     "aside", "figure", "figcaption"]):
                tag.decompose()
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return text

    # フォールバック: body全体
    body = soup.find("body")
    if body:
        for tag in body.find_all(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return body.get_text(separator="\n", strip=True)
    return ""


def _extract_book_info(soup: BeautifulSoup, body_text: str) -> str:
    """書籍タイトルと著者名を抽出する。"""
    # 構造化データ (JSON-LD) から試みる
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") in ("Book", "Product"):
                name = data.get("name", "")
                author = ""
                a = data.get("author")
                if isinstance(a, dict):
                    author = a.get("name", "")
                elif isinstance(a, list) and a:
                    author = a[0].get("name", "")
                if name:
                    return f"{name}（{author}）" if author else name
        except (json.JSONDecodeError, AttributeError, KeyError):
            pass

    # テキストから書籍情報を推定（「著者名 著」「著者名 訳」などのパターン）
    patterns = [
        r"『(.+?)』[（(](.+?)[）)]",
        r"「(.+?)」[（(](.+?)[）)]",
        r"『(.+?)』",
    ]
    for pat in patterns:
        m = re.search(pat, body_text)
        if m:
            if m.lastindex == 2:
                return f"{m.group(1)}（{m.group(2)}）"
            return m.group(1)

    return "不明"


def build_markdown(article: dict) -> str:
    """記事情報からMarkdownを生成する。"""
    title = article["title"]
    pub_date = article["pub_date"]
    url = article["url"]
    book = article["book"]
    body = article["body"]

    return (
        f"# {title}\n\n"
        f"- **公開日**: {pub_date}\n"
        f"- **URL**: {url}\n"
        f"- **書籍**: {book}\n\n"
        f"---\n\n"
        f"{body}\n"
    )


def save_article(article: dict) -> Path:
    """Markdownファイルを保存し、パスを返す。"""
    pub_date = article["pub_date"]
    year, month, *_ = pub_date.split("-")
    date_str = pub_date.replace("-", "")

    safe_title = sanitize_filename(article["title"])
    filename = f"{safe_title}_{date_str}.md"

    dir_path = ARTICLES_DIR / year / month
    dir_path.mkdir(parents=True, exist_ok=True)

    file_path = dir_path / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(build_markdown(article))

    return file_path


def run(full_mode: bool = False) -> None:
    state = load_state()
    collected_set = set(state.get("collected_urls", []))

    print(f"[開始] {'全件取得' if full_mode else '差分取得'}モード")
    print(f"[状態] 収集済みURL: {len(collected_set)}件")

    new_articles = []
    error_urls = []
    page = 1
    stop_crawl = False

    while not stop_crawl:
        if page == 1:
            index_url = INDEX_URL
        else:
            index_url = f"{INDEX_URL}{page}/"

        print(f"[巡回] インデックスページ {page}: {index_url}")
        soup = get_page(index_url)
        if soup is None:
            print(f"  [警告] ページ {page} を取得できませんでした。巡回終了。")
            break

        article_urls = collect_article_urls_from_page(soup)
        if not article_urls:
            print(f"  [情報] ページ {page} に記事URLが見つかりません。巡回終了。")
            break

        print(f"  [発見] {len(article_urls)}件のURL")

        for url in article_urls:
            if url in collected_set:
                if not full_mode:
                    print(f"  [済] 収集済みURLに到達。差分取得完了。")
                    stop_crawl = True
                    break
                continue

            print(f"  [取得] {url}")
            time.sleep(2.5)

            article = scrape_article(url)
            if article is None:
                print(f"  [エラー] スキップ: {url}")
                error_urls.append(url)
                continue

            file_path = save_article(article)
            collected_set.add(url)
            new_articles.append(url)
            print(f"  [保存] {file_path.relative_to(Path(__file__).parent)}")

        if stop_crawl:
            break

        # 次ページへ
        next_link = soup.find("a", string=re.compile(r"次|next|›|»", re.I))
        if next_link is None:
            # ページネーション数値リンクで確認
            page_links = soup.select("a[href*='/regular/regular_book_to_read/']")
            next_page_exists = any(
                f"/regular/regular_book_to_read/{page + 1}/" in (a.get("href", ""))
                for a in page_links
            )
            if not next_page_exists:
                print(f"[情報] 次ページなし。巡回完了。")
                break

        page += 1
        time.sleep(2)

    # state更新
    state["collected_urls"] = list(collected_set)
    state["last_run"] = datetime.now(JST).isoformat()
    save_state(state)

    print(f"\n[完了] 新規取得: {len(new_articles)}件 / エラー: {len(error_urls)}件")
    if error_urls:
        print("[エラーURL一覧]")
        for u in error_urls:
            print(f"  {u}")


def main() -> None:
    parser = argparse.ArgumentParser(description="毎日書評スクレイパー")
    parser.add_argument(
        "--full",
        action="store_true",
        help="全件取得モード（初回セットアップ用）",
    )
    args = parser.parse_args()
    run(full_mode=args.full)


if __name__ == "__main__":
    main()
