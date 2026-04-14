# daily-book-review-scraper

## リポジトリ情報

- **GitHub**: https://github.com/haruten-bt/daily-book-review-scraper
- **アカウント**: haruten-bt
- **プロトコル**: HTTPS

## GitHub プッシュ手順

### 通常のプッシュ

```bash
git add .
git commit -m "コメント"
git push
```

認証は `gh` CLI のキーチェーン経由で自動処理される。

### 初回セットアップ（新規リポジトリ）

```bash
# 1. gh CLI ログイン確認
gh auth status

# 2. リポジトリ作成
gh repo create haruten-bt/<repo-name> --public --description "説明"

# 3. ローカル初期化 & プッシュ
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/haruten-bt/<repo-name>.git

# 4. workflow スコープが必要な場合（.github/workflows/ を含むとき）
gh auth refresh --hostname github.com -s workflow
# → ブラウザでワンタイムコードを入力して認証

# 5. プッシュ（workflow スコープ取得直後は一時的に token 直埋めが必要な場合あり）
gh auth token | xargs -I{} git remote set-url origin "https://{}@github.com/haruten-bt/<repo-name>.git"
git push -u origin main
git remote set-url origin https://github.com/haruten-bt/<repo-name>.git  # URL を元に戻す
```

### トラブルシューティング

| エラー | 原因 | 対処 |
|--------|------|------|
| `refusing to allow an OAuth App to create or update workflow` | `workflow` スコープ不足 | `gh auth refresh --hostname github.com -s workflow` |
| `remote: Repository not found` | リポジトリ未作成 or URL誤り | `gh repo create` / `git remote set-url` で確認 |

---

## このプロジェクトの初回実行

```bash
# 依存インストール
pip install -r requirements.txt

# 全件取得（初回のみ・1,900件以上あるため時間がかかる）
python scraper.py --full

# 週まとめ生成
python aggregator.py
```

GitHub Actions は毎日 9:00 JST に自動実行される。
手動実行は Actions タブ → `Run workflow` から可能（`full_mode` オプション付き）。
