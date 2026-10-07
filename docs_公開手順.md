# 公開手順（GitHub Pages）

このツールで作ったページを、会社PCのブラウザから見られるようにする手順です。
git や GitHub を使ったことがない方向けに書いています。

- コマンドは **Git Bash**（または コマンドプロンプト）で実行します
- 行の先頭の `$` は入力しません。その後ろだけを入力します
- `<ユーザー名>` と書いてある部分は、あなたの GitHub のユーザー名に置き換えます

---

## 用語（最初に3つだけ）

| 言葉 | 意味 |
|---|---|
| リポジトリ | GitHub 上の「このプロジェクト専用の保管場所」 |
| コミット | 変更内容に名前を付けて、手元の履歴に記録すること |
| プッシュ | 手元の記録を GitHub に送ること |

ページが新しくなるのは「プッシュ」をしたときです。

---

## A. 最初の1回だけ行う準備

### A-1. GitHub でリポジトリを作る

1. ブラウザで <https://github.com/new> を開く（会社メールで登録したアカウントでログイン）
2. `Repository name` に **`website-maker`** と入力
3. その下で **`Public`**（公開）を選ぶ
4. `Add a README file` などのチェックは **すべて外したまま** にする
   （中身のあるリポジトリを作ると、あとの手順でぶつかります）
5. 一番下の `Create repository` を押す

次の画面に `https://github.com/<ユーザー名>/website-maker.git` という住所が出ます。この住所を使います。

### A-2. 手元のプロジェクトを GitHub につなげる

Git Bash を開き、次を1行ずつ実行します。

```
$ cd /d/claude_projects/04000_websiteMaker
$ git remote add origin https://github.com/<ユーザー名>/website-maker.git
$ git add .
$ git commit -m "ウェブサイトメーカーの初版"
$ git push -u origin main
```

- `git push` のときに GitHub のログインを求められます。パスワードではなく
  **個人アクセストークン**を聞かれる場合があります。その場合は
  <https://github.com/settings/tokens> で `Generate new token (classic)` を押し、
  `repo` にチェックを入れて作ったトークンを貼り付けます
- トークンは**メモ帳などに保存せず**、ブラウザやコマンド画面から直接貼り付けてください

### A-3. GitHub Pages を有効にする

1. ブラウザで `https://github.com/<ユーザー名>/website-maker` を開く
2. 上のタブの **`Settings`**（歯車のアイコン）をクリック
3. 左のメニューから **`Pages`** をクリック
4. `Build and deployment` の `Source` を **`Deploy from a branch`** にする
5. `Branch` の欄で、左のプルダウンを **`main`**、右のプルダウンを **`/docs`** にする
6. **`Save`** を押す

1〜2分待ってから、次の住所を開きます。

```
https://<ユーザー名>.github.io/website-maker/
```

ページが表示されれば準備完了です。このアドレスをブラウザのお気に入りに入れておいてください。

> 最初の1回だけ、表示されるまで5分ほどかかることがあります。
> `404` が出た場合は、少し待ってから再読み込みしてください。

---

## B. 毎週行うこと（3ステップ）

### B-1. ページを作る

Git Bash で次を実行します。

```
$ cd /d/claude_projects/04000_websiteMaker
$ .venv/Scripts/python.exe src/main.py
```

2〜5分かかります。最後に「ページを作りました」と出て、各セクションの件数が表示されます。

### B-2. GitHub に送る

```
$ git add docs
$ git commit -m "2026-10-07 の回"
$ git push
```

`-m` の後ろは何でもかまいません（日付を入れておくと後で分かりやすいです）。

### B-3. 確認する

1〜2分待ってから `https://<ユーザー名>.github.io/website-maker/` を開きます。
トップページが最新回になり、下に過去回へのリンクが増えています。

---

## よくあるつまずき

| 症状 | 原因と対処 |
|---|---|
| `git push` で `rejected` と出る | GitHub 側に別の変更があります。`git pull --rebase` を実行してから、もう一度 `git push` してください |
| `git commit` で `nothing to commit` と出る | 変更がありません。`src/main.py` を実行し直してください |
| ページが古いまま | `git push` が済んでいない可能性があります。`git status` を実行し、`nothing to commit, working tree clean` と出ているか確認してください |
| `404` が出る | GitHub Pages の設定（A-3）で `/docs` を選べているか確認してください |
| 「Qiita は取得できませんでした」と出た | Qiita のアクセス上限（1時間60回）に当たった可能性があります。1時間待って実行し直すか、`.env` に `QIITA_TOKEN` を設定してください |
| 「note は取得できませんでした」と出た | note の非公式な取得方法が変わった可能性があります。他のセクションはそのまま表示されます |

---

## 設定の変え方（プログラムは直しません）

| 変えたいこと | 開くファイル | やり方 |
|---|---|---|
| セクションのキーワード | `keywords.txt` | メモ帳で開いて1行1キーワードで書く。書いた順がページの順番になる |
| AI判定に使う単語 | `ai_trend_words.txt` | メモ帳で開いて1行1単語で書く。要らない行は先頭に `#` を付ける |
| Qiita のアクセス上限を増やす | `.env` | `QIITA_TOKEN=` の後ろにトークンを書く（省略可） |
| はてブで拾う最低ブックマーク数 | `.env` | `HATENA_MIN_USERS=10` の数字を変える（省略時は 10） |

変更したら `src/main.py` を実行し直して、`git push` すれば反映されます。

### `.env` について

`.env` はパスワードのような情報を書くファイルです。
`.gitignore` で除外しているので **GitHub には上がりません**。

まだ `.env` が無い場合は、`.env.example` をコピーして `.env` という名前に変え、中身を編集してください。
どちらの項目も省略できます（空のままでも動きます）。

---

## 公開されるもの・されないもの

リポジトリは公開（Public）なので、**GitHub に送ったものは誰でも見られます。**

| | 中身 |
|---|---|
| 公開される | `src/`（プログラム）、`tests/`、`docs/`（ページ）、`keywords.txt`、`ai_trend_words.txt`、`pyproject.toml`、`requirements.txt` |
| 公開されない | `00_memo/`（要件メモ・設計メモ）、`.env`（トークン）、`.venv/`、`tmp_probe/` |

公開されないものは `.gitignore` に書いてあります。
**新しく秘密の情報を扱うときは、必ず `.env` に書いてください。**
