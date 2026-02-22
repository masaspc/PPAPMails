# Secure Download

**PPAP対策 メール添付ファイル セキュアダウンロードシステム（Azure版）**

PPAP（Password付きZIPファイルをメールで送付する運用）対策として、メール添付ファイルを自動的にURLダウンロード方式に変換するシステムです。

## 目次

- [システム概要](#システム概要)
- [アーキテクチャ](#アーキテクチャ)
- [メール処理フロー](#メール処理フロー)
- [機能一覧](#機能一覧)
- [技術スタック](#技術スタック)
- [ディレクトリ構成](#ディレクトリ構成)
- [前提条件](#前提条件)
- [デプロイ手順](#デプロイ手順)
- [ローカル開発環境](#ローカル開発環境)
- [API リファレンス](#api-リファレンス)
- [運用手順](#運用手順)
- [トラブルシューティング](#トラブルシューティング)
- [データベース設計](#データベース設計)
- [セキュリティ](#セキュリティ)
- [コスト](#コスト)

---

## システム概要

社外宛てメールに添付ファイルがある場合、Exchange Online のメールフロールールで検知し、処理用メールボックスへリダイレクトします。Azure Functions が Graph API 経由でメールを取得・処理し、添付ファイルを Azure Blob Storage に暗号化保存、ダウンロード用URLに置換した再構築メールを受信者へ送信します。

```
送信者 (Outlook)
    |
    v
Exchange Online
    |  メールフロールール（添付付き社外宛て）
    v
処理用メールボックス (process@example.com)
    |
    v
Azure Functions (Timer Trigger: 30秒間隔)
    |- Graph API でメール取得
    |- 添付ファイル分離
    |- AES-256暗号化 -> Azure Blob Storage に保存
    +- URL付きメール再構築 -> Graph API で送信
    |
    v
受信者がURLアクセス (Azure App Service)
    |- メアド入力 -> 認証コード受信
    |- コード入力 -> 認証完了
    +- ファイルダウンロード
```

## アーキテクチャ

### Azure インフラ構成

```
Exchange Online
    |  メールフロールール -> 処理用メールボックスへリダイレクト
    v
+----------------------------------------------------------+
|  Azure                                                    |
|                                                           |
|  +------------------------+  +-------------------------+  |
|  | Azure Functions        |  | Azure App Service       |  |
|  | (Consumption/B1)       |  | (B1 Linux Python)       |  |
|  |                        |  |                          |  |
|  | - process_email        |  | FastAPI (Gunicorn)      |  |
|  |   (Timer: 30秒)        |  | - ダウンロードポータル   |  |
|  | - cleanup_timer        |  | - 送信者ダッシュボード   |  |
|  |   (Timer: 毎日3:00)    |  | - 管理者ダッシュボード   |  |
|  | - health_check (HTTP)  |  | - 内部API               |  |
|  +----------+-------------+  +-----------+--------------+  |
|             |                            |                 |
|             v                            v                 |
|  +------------------------------------------------------+  |
|  |  Azure Database for PostgreSQL Flexible Server        |  |
|  |  (Burstable B1ms, 自動バックアップ7日, SSL必須)       |  |
|  +------------------------------------------------------+  |
|  +------------------------------------------------------+  |
|  |  Azure Blob Storage (Standard LRS)                    |  |
|  |  暗号化済みファイル保管 (SSE + アプリ暗号化)           |  |
|  +------------------------------------------------------+  |
|  +------------------------------------------------------+  |
|  |  Azure Monitor + Application Insights                 |  |
|  |  ログ集約・アラート・パフォーマンス監視                |  |
|  +------------------------------------------------------+  |
|  +------------------------------------------------------+  |
|  |  Microsoft Entra ID                                   |  |
|  |  送信者/管理者画面のSSO認証, Graph API認証             |  |
|  +------------------------------------------------------+  |
+----------------------------------------------------------+
    |
[インターネット] --- [download.example.com]
```

### コンポーネント対応表

| 機能 | Azure サービス | 役割 |
|------|---------------|------|
| メール受信・処理 | Azure Functions (Timer) | Graph APIで処理用メールボックスをポーリング |
| Webアプリ | Azure App Service (Linux) | FastAPI ダウンロードポータル・管理画面 |
| データベース | Azure Database for PostgreSQL | トランザクションデータ保管 |
| ファイル保管 | Azure Blob Storage | 暗号化済み添付ファイル保管 |
| 定期タスク | Azure Functions (Timer) | 期限切れファイル削除 |
| 認証 | Microsoft Entra ID (MSAL) | 送信者/管理者のSSO認証 |
| メール送信 | Microsoft Graph API | 再構築メール・認証コード送信 |
| 監視・ログ | Azure Monitor + App Insights | ログ集約・アラート |
| IaC | Bicep | インフラのコード管理 |
| CI/CD | GitHub Actions | 自動テスト・デプロイ |

## メール処理フロー

### 送信側

1. 送信者が通常通りファイル添付メールをOutlookから送信
2. Exchange Onlineのメールフロールールで添付ファイル付き社外宛てメールを検知
3. 処理用メールボックス (`process@example.com`) へリダイレクト
4. Azure Functions が30秒間隔で処理用メールボックスをポーリング（Graph API）
5. 未読の添付ファイル付きメールを検出、添付ファイルを分離
6. AES-256暗号化 → Azure Blob Storage に保管
7. ファイルごとにUUID v4ベースのダウンロードURLを生成
8. 元のメール本文を保持し、添付部分をダウンロードURL一覧に置換
9. Microsoft Graph APIで再構築メールを受信者に送信
10. 処理済みメールを既読にマーク

### ダウンロード側

1. 受信者がURLにアクセス（Azure App Service → FastAPI）
2. メールアドレスを入力（To/CC/BCCに含まれるアドレスのみ許可）
3. 6桁の認証コードがメールで届く（有効期限10分）
4. コードを入力 → 認証成功
5. ファイル一覧が表示され、ダウンロード可能に
6. 認証状態はCookieで14日間保持（再認証不要）

## 機能一覧

| 機能 | 説明 |
|------|------|
| 添付ファイル自動分離 | メールから添付ファイルを検出し自動分離 |
| AES-256暗号化保存 | Fernet (AES-256-CBC) でファイルを暗号化してBlob Storageに保管 |
| メールアドレス認証 | 6桁ワンタイム認証コード（10分有効、5回失敗でロック） |
| Cookie認証保持 | 認証後14日間はCookieで再認証不要 |
| ダウンロード回数制限 | ファイルごとに最大10回（管理画面で変更可能） |
| 有効期限 | 送信から30日でURL無効化＋ファイル自動削除 |
| URL無効化（誤送信対策） | 送信者が即座にURLを無効化可能 |
| 送信者ダッシュボード | 送信履歴・DL状況・受信者別ログ |
| 管理者ダッシュボード | 全社統計・設定変更・除外ドメイン・監査ログ |
| 除外ドメイン | 特定ドメイン宛てはセキュアDL変換対象外に設定可能 |
| 監査ログ | 全操作を記録、CSV出力対応 |
| IPレート制限 | 30回/分（設定変更可能） |

## 技術スタック

| レイヤー | 技術 | バージョン |
|---------|------|----------|
| 言語 | Python | 3.12 |
| Webフレームワーク | FastAPI | 0.115+ |
| ASGI/WSGI | Gunicorn + Uvicorn | 22.0+ / 0.30+ |
| データベース | PostgreSQL (Azure Flexible Server) | 16 |
| ORM | SQLAlchemy (async) | 2.0+ |
| マイグレーション | Alembic | 1.13+ |
| テンプレート | Jinja2 + TailwindCSS | 3.1+ |
| 暗号化 | cryptography (Fernet) | 42.0+ |
| メール送信 | Microsoft Graph API (MSAL) | - |
| 認証 | Microsoft Entra ID (MSAL) | - |
| ファイル保管 | Azure Blob Storage | 12.19+ |
| バックグラウンド処理 | Azure Functions (Python v2) | 4.x |
| 監視 | Azure Monitor + App Insights | - |
| IaC | Bicep | - |
| CI/CD | GitHub Actions | - |

## ディレクトリ構成

```
PPAPMails/
├── app/
│   ├── main.py                    # FastAPIエントリポイント
│   ├── config.py                  # 環境変数設定管理
│   ├── database.py                # DB接続・セッション管理
│   ├── models/                    # SQLAlchemy モデル
│   ├── schemas/                   # Pydantic バリデーション
│   ├── routers/                   # APIルーター
│   ├── services/                  # ビジネスロジック
│   │   ├── email_processor.py     #   メール受信・分離・再構築
│   │   ├── file_manager.py        #   ファイル暗号化・保管 (Blob/ローカル)
│   │   ├── auth_service.py        #   認証コード生成・検証
│   │   ├── graph_api.py           #   Graph API メール送信
│   │   ├── notification.py        #   通知メール生成
│   │   └── cleanup.py             #   期限切れ自動削除
│   ├── middleware/                # 認証・レート制限
│   └── templates/                 # Jinja2 HTMLテンプレート
├── azure_functions/               # Azure Functions
│   ├── function_app.py            #   エントリポイント
│   ├── process_email.py           #   メール処理 (Timer: 30秒)
│   ├── cleanup_timer.py           #   期限切れ削除 (Timer: 毎日)
│   ├── health_check.py            #   ヘルスチェック (HTTP)
│   ├── host.json                  #   Functions設定
│   └── requirements.txt           #   Functions用依存パッケージ
├── migrations/                    # Alembic マイグレーション
├── tests/                         # ユニットテスト
├── deploy/azure/                  # Azure IaC
│   ├── main.bicep                 #   Bicep テンプレート
│   └── parameters.example.json    #   パラメータ例
├── .github/workflows/
│   └── deploy-azure.yml           #   CI/CD パイプライン
├── .env.example
├── requirements.txt
└── pyproject.toml
```

## 前提条件

### Azure
- Azure サブスクリプション
- Azure CLI (`az`) インストール済み

### Microsoft 365
- Microsoft 365 Business Standard / Exchange Online
- Microsoft Entra ID
- Azure ポータルでアプリ登録 x 2件（Graph API用 / Web認証用）
- 処理用メールボックス（共有メールボックスまたは専用ユーザー）

---

## デプロイ手順

### Step 1: Microsoft Entra ID 設定

#### アプリ登録 1: Graph API用（メール送信 + メール読み取り）

1. Azure Portal > Microsoft Entra ID > アプリの登録 > 新規登録
2. 名前: `Secure Download - Graph API`
3. アカウントの種類: この組織のアカウントのみ
4. APIのアクセス許可（アプリケーション権限）:
   - `Mail.Send` — 再構築メール・認証コードの送信
   - `Mail.Read` — 処理用メールボックスの読み取り
   - `Mail.ReadWrite` — 処理済みメールの既読マーク
5. 管理者の同意を付与
6. クライアントシークレットを作成
7. メモ: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`

#### アプリ登録 2: Web認証用

1. 名前: `Secure Download - Web`
2. リダイレクトURI: `https://download.example.com/auth/callback`
3. APIのアクセス許可（委任権限）: `User.Read`, `GroupMember.Read.All`
4. クライアントシークレットを作成
5. メモ: `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`

#### 管理者グループ・処理用メールボックスの作成

- Entra ID > グループで `Secure Download Admins` を作成 → `ADMIN_GROUP_ID`
- Exchange管理センターで共有メールボックス `process@example.com` を作成 → `PROCESSING_MAILBOX`

### Step 2: Azure リソースのデプロイ

```bash
az login
az group create --name rg-secure-download --location japaneast

cp deploy/azure/parameters.example.json deploy/azure/parameters.json
# parameters.json を実際の値で編集

az deployment group create \
    --resource-group rg-secure-download \
    --template-file deploy/azure/main.bicep \
    --parameters deploy/azure/parameters.json
```

### Step 3: アプリケーションデプロイ

```bash
# DBマイグレーション
pip install -r requirements.txt
export DATABASE_URL_SYNC="postgresql://pgadmin:<password>@<host>:5432/secure_download?sslmode=require"
alembic -c migrations/alembic.ini upgrade head

# App Service デプロイ
zip -r app.zip app/ migrations/ requirements.txt pyproject.toml
az webapp deploy --resource-group rg-secure-download --name app-sd-prod --src-path app.zip --type zip

# Azure Functions デプロイ
cd azure_functions
func azure functionapp publish func-sd-prod --python
```

### Step 4: Exchange Online 設定

1. Exchange管理センター > メールフロー > ルール > 追加
2. ルール名: `セキュアダウンロード転送`
3. 条件: 送信者が組織内 + 受信者が組織外 + 添付ファイルあり
4. アクション: メッセージを `process@example.com` にリダイレクト

> SMTPコネクタは不要です。Exchange Online内の処理用メールボックスへのリダイレクトのみで動作します。

### Step 5: カスタムドメイン・監視設定

```bash
# カスタムドメイン追加
az webapp config hostname add \
    --resource-group rg-secure-download \
    --webapp-name app-sd-prod \
    --hostname download.example.com

# SSL証明書（App Service Managed Certificate）
az webapp config ssl create \
    --resource-group rg-secure-download \
    --name app-sd-prod \
    --hostname download.example.com
```

DNS: `download.example.com` CNAME → `app-sd-prod.azurewebsites.net`

---

## ローカル開発環境

```bash
git clone https://github.com/masaspc/PPAPMails.git && cd PPAPMails
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env: APP_DEBUG=true, STORAGE_BACKEND=local, STORAGE_PATH=./uploaded_files

# DB作成・マイグレーション
sudo -u postgres createuser app_user
sudo -u postgres createdb -O app_user secure_download
alembic -c migrations/alembic.ini upgrade head

# 開発サーバー起動
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

テスト・品質チェック:
```bash
pytest --cov=app --cov-report=html
ruff check app/ tests/
mypy app/
```

---

## API リファレンス

### ダウンロードポータル（受信者向け）

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/d/{token}` | ダウンロードページ |
| POST | `/d/{token}/request-code` | 認証コードリクエスト |
| POST | `/d/{token}/verify` | 認証コード検証 |
| GET | `/d/{token}/download/{id}` | ファイルダウンロード |

### 送信者向け（Entra ID認証必須）

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/sender/` | 送信履歴一覧 |
| GET | `/sender/transfer/{id}` | 送信詳細 |
| POST | `/sender/transfer/{id}/revoke` | URL無効化 |

### 管理者向け（Entra ID + 管理者グループ）

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/admin/` | ダッシュボード |
| GET/PUT | `/admin/settings` | システム設定 |
| GET/POST/DELETE | `/admin/excluded-domains` | 除外ドメイン管理 |
| GET | `/admin/audit-logs` | 監査ログ |
| GET | `/admin/audit-logs/export` | CSV出力 |

### 内部API

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/internal/process-email` | メール処理 |
| GET | `/internal/health` | ヘルスチェック |

---

## 運用手順

### デプロイ
GitHub Actions で `main` ブランチへのプッシュ時に自動デプロイされます。

### 定期タスク

| タスク | 頻度 | 実行元 |
|--------|------|--------|
| メールポーリング | 30秒間隔 | Azure Functions `process_email_timer` |
| 期限切れ削除 | 毎日 JST 3:00 | Azure Functions `cleanup_timer` |
| DBバックアップ | 自動 (7日保持) | Azure PostgreSQL 組み込み |
| SSL更新 | 自動 | App Service Managed Certificate |

### バックアップ・リストア

```bash
# ポイントインタイムリストア
az postgres flexible-server restore \
    --resource-group rg-secure-download \
    --name psql-sd-prod-restored \
    --source-server psql-sd-prod \
    --restore-time "2025-01-15T10:00:00Z"
```

---

## トラブルシューティング

### メールが処理されない
```bash
az webapp log tail --resource-group rg-secure-download --name func-sd-prod
```

### ダウンロードできない
```bash
az webapp log tail --resource-group rg-secure-download --name app-sd-prod
az storage blob list --account-name stsdprod --container-name secure-downloads --output table
```

### DB接続エラー
```bash
az postgres flexible-server firewall-rule list \
    --resource-group rg-secure-download --name psql-sd-prod
```

---

## データベース設計

```
transfers -+-- recipients (1:N)
            +-- attachments (1:N) -- download_logs (1:N)
            +-- auth_codes (1:N)
            +-- auth_sessions (1:N)

system_settings (独立)
excluded_domains (独立)
audit_logs (独立)
```

---

## セキュリティ

| 対策 | 実装 |
|------|------|
| ファイル暗号化 | AES-256 (Fernet) + Azure SSE |
| 通信暗号化 | HTTPS必須 (TLS 1.2+) |
| 認証コード | 6桁ワンタイム、10分有効、5回でロック |
| URL推測防止 | UUID v4 (122ビットランダム) |
| レート制限 | IP制限 30回/分 |
| DB暗号化 | PostgreSQL SSL必須 |
| Blob Storage | パブリックアクセス無効 |
| 秘匿情報 | App Service設定（暗号化保存） |
| 認証 | Entra ID SSO + グループベース権限 |

---

## コスト

### 月額ランニングコスト

| 項目 | SKU | 月額概算 |
|------|-----|---------|
| App Service | B1 (Linux) | 約1,900円 |
| PostgreSQL Flexible Server | Burstable B1ms | 約2,500円 |
| Blob Storage | Standard LRS | 約100円 |
| Azure Functions | Consumption | 約0円 (無料枠内) |
| Application Insights | 従量課金 | 約100円 |
| **合計** | | **約4,600円/月** |

### 年間コスト比較

| 構成 | 年間コスト |
|------|-----------|
| HENNGE One DLP | 約412,800円 |
| 本システム（ConoHa VPS版） | 約33,876円 |
| **本システム（Azure PaaS版）** | **約55,200円** |

> **Azure版の追加メリット**: OS/ミドルウェア管理不要、自動バックアップ、SMTPサーバー不要、Blob Storageによるファイル共有（lsyncd不要）、Entra IDネイティブ統合、スケーラビリティ、CI/CD、統合監視

---

## ライセンス

Proprietary
