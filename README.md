# TBN Secure Download

**PPAP対策 メール添付ファイル セキュアダウンロードシステム**

東京ベイネットワーク株式会社のPPAP（Password付きZIPファイルをメールで送付する運用）対策として、メール添付ファイルを自動的にURLダウンロード方式に変換するシステムです。

## 目次

- [システム概要](#システム概要)
- [アーキテクチャ](#アーキテクチャ)
- [メール処理フロー](#メール処理フロー)
- [機能一覧](#機能一覧)
- [技術スタック](#技術スタック)
- [ディレクトリ構成](#ディレクトリ構成)
- [前提条件](#前提条件)
- [デプロイ手順](#デプロイ手順)
  - [Step 1: VPS初期セットアップ](#step-1-vps初期セットアップ)
  - [Step 2: PostgreSQLセットアップ](#step-2-postgresqlセットアップ)
  - [Step 3: アプリケーションデプロイ](#step-3-アプリケーションデプロイ)
  - [Step 4: Nginx + SSL設定](#step-4-nginx--ssl設定)
  - [Step 5: Postfix設定](#step-5-postfix設定)
  - [Step 6: 2台目VPS（冗長化）](#step-6-2台目vps冗長化)
  - [Step 7: Exchange Online設定](#step-7-exchange-online設定)
  - [Step 8: Microsoft Entra ID設定](#step-8-microsoft-entra-id設定)
  - [Step 9: 監視・セキュリティ設定](#step-9-監視セキュリティ設定)
- [ローカル開発環境](#ローカル開発環境)
- [API リファレンス](#api-リファレンス)
- [運用手順](#運用手順)
  - [ゼロダウンタイムアップデート](#ゼロダウンタイムアップデート)
  - [DBフェイルオーバー](#dbフェイルオーバー)
  - [バックアップとリストア](#バックアップとリストア)
  - [定期メンテナンス](#定期メンテナンス)
- [トラブルシューティング](#トラブルシューティング)
- [データベース設計](#データベース設計)
- [セキュリティ](#セキュリティ)
- [コスト](#コスト)

---

## システム概要

社外宛てメールに添付ファイルがある場合、Exchange Online のメールフロールールで検知し、ConoHa VPS 上の本システムへリダイレクトします。本システムは添付ファイルを分離・暗号化保存し、ダウンロード用URLに置換した再構築メールを受信者へ送信します。受信者はURLにアクセスし、メールアドレス認証を経てファイルをダウンロードします。

```
送信者 (Outlook)
    │
    ▼
Exchange Online ──メールフロールール──▶ ConoHa VPS (Postfix)
                                           │
                                           ▼
                                      Python処理
                                      ├─ 添付ファイル分離
                                      ├─ AES-256暗号化保存
                                      └─ URL付きメール再構築
                                           │
                                           ▼
                                      Graph API でメール送信
                                      ├─ 受信者へURL付きメール
                                      └─ 認証コードメール（DL時）
                                           │
                                           ▼
                                      受信者がURLアクセス
                                      ├─ メアド入力 → 認証コード受信
                                      ├─ コード入力 → 認証完了
                                      └─ ファイルダウンロード
```

## アーキテクチャ

### インフラ構成（Active-Active 2台冗長）

```
Exchange Online
    │  SMTPコネクタ（2台のVPS IP登録 → 自動フェイルオーバー）
    │
    ├────────────────────┬────────────────────┐
    │                    │                    │
[VPS1: Active]      [VPS2: Active]           │
 Postfix(SMTP)       Postfix(SMTP)           │
 Nginx               Nginx                   │
 Gunicorn+FastAPI    Gunicorn+FastAPI        │
 PostgreSQL          PostgreSQL              │
 (Primary)           (Standby/レプリカ)      │
    │                    │                    │
    └── lsyncd (ファイル双方向同期) ──────┘   │
    └── Streaming Replication ────────┘      │
                                              │
[ConoHa ロードバランサー] ───────────────────┘
    │  ヘルスチェック + 自動切替
    │
[インターネット] ─── [download.tbnet.jp]
```

| コンポーネント | 冗長化方式 |
|--------------|----------|
| SMTP受信 | Exchange コネクタに2台登録（自動フェイルオーバー） |
| Web/API | ConoHaロードバランサー（ヘルスチェック付き） |
| データベース | PostgreSQL Streaming Replication |
| ファイルストレージ | lsyncd + rsync（プライベートNW経由） |
| 認証セッション | DB保存（どちらのVPSでも認証維持） |

## メール処理フロー

### 送信側

1. 送信者が通常通りファイル添付メールをOutlookから送信
2. Exchange Onlineのメールフロールールで添付ファイル付き社外宛てメールを検知
3. SMTPコネクタ経由でConoHa VPS上のPostfixへリダイレクト
4. Postfixが受信後、`mail_handler/postfix_handler.py` でメール処理APIをコール
5. 添付ファイルを分離 → AES-256暗号化 → ローカルディスクに保管（lsyncdで2台間同期）
6. ファイルごとにUUID v4ベースのダウンロードURLを生成
7. 元のメール本文を保持し、添付部分をダウンロードURL一覧に置換
8. Microsoft Graph APIで再構築メールを受信者に送信

### ダウンロード側

1. 受信者がURLにアクセス（ConoHa LB経由でNginx → FastAPI）
2. メールアドレスを入力（To/CC/BCCに含まれるアドレスのみ許可）
3. 6桁の認証コードがメールで届く（有効期限10分）
4. コードを入力 → 認証成功
5. ファイル一覧が表示され、ダウンロード可能に
6. 認証状態はCookieで14日間保持（再認証不要）

## 機能一覧

| 機能 | 説明 |
|------|------|
| 添付ファイル自動分離 | メールから添付ファイルを検出し自動分離 |
| AES-256暗号化保存 | Fernet (AES-256-CBC) でファイルを暗号化してディスクに保管 |
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
| fail2ban連携 | 認証失敗多発IPを自動ブロック |

## 技術スタック

| レイヤー | 技術 | バージョン |
|---------|------|----------|
| OS | Ubuntu | 24.04 LTS |
| 言語 | Python | 3.12 |
| Webフレームワーク | FastAPI | 0.115+ |
| ASGI/WSGI | Gunicorn + Uvicorn | 22.0+ / 0.30+ |
| データベース | PostgreSQL | 16 |
| ORM | SQLAlchemy (async) | 2.0+ |
| マイグレーション | Alembic | 1.13+ |
| テンプレート | Jinja2 + TailwindCSS | 3.1+ |
| 暗号化 | cryptography (Fernet) | 42.0+ |
| メール送信 | Microsoft Graph API (MSAL) | - |
| 認証 | Microsoft Entra ID (MSAL) | - |
| リバースプロキシ | Nginx | - |
| MTA | Postfix | - |
| SSL | Let's Encrypt (certbot) | - |
| ファイル同期 | lsyncd + rsync | - |

## ディレクトリ構成

```
/opt/tbn-secure-download/          ← デプロイ先
├── app/
│   ├── main.py                    # FastAPIエントリポイント
│   ├── config.py                  # 環境変数設定管理
│   ├── database.py                # DB接続・セッション管理
│   ├── models/                    # SQLAlchemy モデル（9テーブル）
│   │   ├── transfer.py            #   送信履歴
│   │   ├── recipient.py           #   受信者
│   │   ├── attachment.py          #   添付ファイル
│   │   ├── auth_code.py           #   認証コード
│   │   ├── auth_session.py        #   認証セッション
│   │   ├── download_log.py        #   ダウンロードログ
│   │   ├── system_setting.py      #   システム設定
│   │   ├── excluded_domain.py     #   除外ドメイン
│   │   └── audit_log.py           #   監査ログ
│   ├── schemas/                   # Pydantic バリデーション
│   │   ├── download.py            #   ダウンロードポータル用
│   │   ├── sender.py              #   送信者画面用
│   │   ├── admin.py               #   管理者画面用
│   │   └── internal.py            #   内部API用
│   ├── routers/                   # APIルーター
│   │   ├── download.py            #   /d/ 受信者向け
│   │   ├── sender.py              #   /sender/ 送信者向け
│   │   ├── admin.py               #   /admin/ 管理者向け
│   │   └── internal.py            #   /internal/ 内部API
│   ├── services/                  # ビジネスロジック
│   │   ├── email_processor.py     #   メール受信・分離・再構築
│   │   ├── file_manager.py        #   ファイル暗号化・保管
│   │   ├── auth_service.py        #   認証コード生成・検証
│   │   ├── graph_api.py           #   Graph API メール送信
│   │   ├── notification.py        #   通知メール生成
│   │   └── cleanup.py             #   期限切れ自動削除
│   ├── middleware/
│   │   ├── rate_limiter.py        #   IPレート制限
│   │   └── auth.py                #   Entra ID認証
│   └── templates/                 # Jinja2 HTMLテンプレート
│       ├── base.html
│       ├── download/              #   ダウンロードポータルUI
│       ├── sender/                #   送信者ダッシュボードUI
│       └── admin/                 #   管理者ダッシュボードUI
├── mail_handler/
│   └── postfix_handler.py         # Postfix transport hook
├── scripts/
│   ├── cleanup_expired.py         # cron: 期限切れ削除
│   ├── db_backup.py               # cron: DBバックアップ
│   └── health_check.py            # cron: 相互ヘルスチェック
├── migrations/                    # Alembic マイグレーション
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial.py
├── tests/                         # ユニットテスト
├── deploy/                        # デプロイ用設定ファイル
│   ├── nginx/
│   ├── systemd/
│   ├── postfix/
│   ├── postgresql/
│   ├── lsyncd/
│   ├── certbot/
│   └── fail2ban/
├── .env.example                   # 環境変数テンプレート
├── requirements.txt
└── pyproject.toml
```

## 前提条件

### インフラ

- ConoHa VPS 2GBプラン × 2台（Ubuntu 24.04 LTS）
- ConoHa ロードバランサー × 1
- ConoHa プライベートネットワーク（無料）
- 独自ドメイン（例: `download.tbnet.jp`）のDNS設定済み

### Microsoft 365

- Microsoft 365 Business Standard / Exchange Online
- Microsoft Entra ID（旧 Azure AD）
- Azure ポータルでアプリ登録 × 2件（Graph API用 / Web認証用）

### ネットワーク

- VPS のグローバルIP × 2台分
- プライベートネットワークの設定済み
- ポート 80, 443, 25, SSH のファイアウォール許可

---

## デプロイ手順

### Step 1: VPS初期セットアップ

**※ VPS1, VPS2 の両方で実施**

```bash
# システムアップデート
sudo apt update && sudo apt upgrade -y

# 必要パッケージのインストール
sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    postgresql-16 postgresql-client-16 \
    nginx certbot python3-certbot-nginx \
    postfix \
    lsyncd rsync \
    fail2ban ufw \
    git curl

# アプリケーション用ユーザー作成
sudo useradd -r -m -s /bin/bash tbn-app

# ディレクトリ作成
sudo mkdir -p /opt/tbn-secure-download
sudo mkdir -p /var/tbn-secure-download/{files,mail_spool,backups}
sudo mkdir -p /var/log/tbn-secure-download
sudo mkdir -p /var/lib/postgresql/archive

# 権限設定
sudo chown -R tbn-app:tbn-app /opt/tbn-secure-download
sudo chown -R tbn-app:tbn-app /var/tbn-secure-download
sudo chown -R tbn-app:tbn-app /var/log/tbn-secure-download

# ファイアウォール設定
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 25/tcp
# プライベートNW（VPS間通信用）
sudo ufw allow from <PEER_PRIVATE_IP> to any port 5432   # PostgreSQL
sudo ufw allow from <PEER_PRIVATE_IP> to any port 22     # rsync/SSH
sudo ufw enable

# 自動セキュリティアップデート
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### Step 2: PostgreSQLセットアップ

#### VPS1（Primary）

```bash
# PostgreSQLユーザー・DB作成
sudo -u postgres psql <<SQL
CREATE USER tbn_app WITH PASSWORD 'YOUR_SECURE_PASSWORD';
CREATE DATABASE tbn_secure_download OWNER tbn_app;
GRANT ALL PRIVILEGES ON DATABASE tbn_secure_download TO tbn_app;

-- レプリケーション用ユーザー
CREATE USER replicator WITH REPLICATION PASSWORD 'REPLICATOR_PASSWORD';
SQL

# PostgreSQL設定をコピー
sudo cp deploy/postgresql/primary.conf /etc/postgresql/16/main/conf.d/tbn-replication.conf
# ${PRIVATE_IP} を VPS1 のプライベートIPに書き換え
sudo sed -i "s/\${PRIVATE_IP}/10.0.0.1/" /etc/postgresql/16/main/conf.d/tbn-replication.conf

# pg_hba.conf にレプリケーション許可を追加
echo "host  replication  replicator  <VPS2_PRIVATE_IP>/32  md5" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
echo "host  tbn_secure_download  tbn_app  127.0.0.1/32  md5" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf

# アーカイブディレクトリ
sudo mkdir -p /var/lib/postgresql/archive
sudo chown postgres:postgres /var/lib/postgresql/archive

# PostgreSQL再起動
sudo systemctl restart postgresql
```

#### VPS2（Standby）

```bash
# PostgreSQL停止
sudo systemctl stop postgresql

# データディレクトリをクリア
sudo rm -rf /var/lib/postgresql/16/main/*

# Primaryからベースバックアップ
sudo -u postgres pg_basebackup \
    -h <VPS1_PRIVATE_IP> \
    -U replicator \
    -D /var/lib/postgresql/16/main \
    -P -R

# Standby設定をコピー
sudo cp deploy/postgresql/standby.conf /etc/postgresql/16/main/conf.d/tbn-replication.conf

# standby.signal の存在を確認
ls -la /var/lib/postgresql/16/main/standby.signal

# PostgreSQL起動
sudo systemctl start postgresql
```

#### レプリケーション確認（VPS1で実行）

```sql
-- Primary側でレプリケーション状態を確認
SELECT pid, state, client_addr, sent_lsn, write_lsn, flush_lsn
FROM pg_stat_replication;
```

### Step 3: アプリケーションデプロイ

**※ VPS1, VPS2 の両方で実施**

```bash
# リポジトリをクローン
cd /opt/tbn-secure-download
sudo -u tbn-app git clone https://github.com/masaspc/PPAPMails.git .

# Python仮想環境の作成と依存パッケージインストール
sudo -u tbn-app python3.12 -m venv venv
sudo -u tbn-app ./venv/bin/pip install -r requirements.txt

# 環境変数ファイルの作成
sudo -u tbn-app cp .env.example .env
sudo -u tbn-app chmod 600 .env
```

#### .env ファイルの編集

```bash
sudo -u tbn-app nano .env
```

以下の値を実際の値に設定します:

```env
# アプリケーション
APP_SECRET_KEY=<生成: python3 -c "import secrets; print(secrets.token_urlsafe(64))">
PORTAL_DOMAIN=download.tbnet.jp

# データベース
DATABASE_URL=postgresql+asyncpg://tbn_app:YOUR_SECURE_PASSWORD@localhost:5432/tbn_secure_download
DATABASE_URL_SYNC=postgresql://tbn_app:YOUR_SECURE_PASSWORD@localhost:5432/tbn_secure_download

# ファイル暗号化キー
ENCRYPTION_KEY=<生成: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Microsoft Graph API（Step 8で取得した値）
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GRAPH_SENDER_EMAIL=noreply@tbnet.jp

# Entra ID認証（Step 8で取得した値）
ENTRA_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ENTRA_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ENTRA_REDIRECT_URI=https://download.tbnet.jp/auth/callback
ADMIN_GROUP_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

> **重要**: `ENCRYPTION_KEY` は **2台のVPSで同じ値** を設定してください。異なるキーではファイルの復号ができません。

#### データベースマイグレーション（VPS1のみ）

```bash
cd /opt/tbn-secure-download
sudo -u tbn-app ./venv/bin/alembic -c migrations/alembic.ini upgrade head
```

#### systemdサービス登録

```bash
# FastAPIアプリケーション
sudo cp deploy/systemd/tbn-secure-download.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tbn-secure-download
sudo systemctl start tbn-secure-download

# 起動確認
sudo systemctl status tbn-secure-download
curl http://127.0.0.1:8000/internal/health
# → {"status":"ok","database":"ok","storage":"ok","version":"1.0.0"}
```

### Step 4: Nginx + SSL設定

**※ VPS1, VPS2 の両方で実施**

```bash
# SSL証明書の取得（初回のみ）
sudo certbot certonly --standalone -d download.tbnet.jp

# Nginx設定をコピー
sudo cp deploy/nginx/tbn-secure-download.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/tbn-secure-download.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 設定テスト
sudo nginx -t

# Nginx起動
sudo systemctl enable nginx
sudo systemctl restart nginx

# SSL自動更新フック
sudo cp deploy/certbot/renewal-hook.sh /etc/letsencrypt/renewal-hooks/deploy/tbn-reload.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/tbn-reload.sh

# certbot自動更新テスト
sudo certbot renew --dry-run
```

#### ConoHaロードバランサー設定

ConoHaコントロールパネルで以下を設定:

1. ロードバランサーを作成
2. リスナー: ポート80, 443
3. バランシング方式: リーストコネクション
4. ヘルスモニタ: HTTP, パス `/internal/health`, 間隔 30秒
5. メンバー: VPS1, VPS2 のグローバルIP
6. ドメイン `download.tbnet.jp` のAレコードをLBのIPに設定

### Step 5: Postfix設定

**※ VPS1, VPS2 の両方で実施**

```bash
# Postfix設定
sudo cp deploy/postfix/main.cf.template /etc/postfix/main.cf
# ${PEER_VPS_IP} を相手VPSのプライベートIPに書き換え
sudo sed -i "s/\${PEER_VPS_IP}/<PEER_PRIVATE_IP>/" /etc/postfix/main.cf

# Transport map設定
sudo cp deploy/postfix/transport.template /etc/postfix/transport
sudo postmap /etc/postfix/transport

# Exchange Online IPリスト作成
# https://learn.microsoft.com/ja-jp/microsoft-365/enterprise/urls-and-ip-address-ranges
sudo cat > /etc/postfix/exchange_ips <<'EOF'
# Exchange Online送信IPレンジ
40.92.0.0/15    OK
40.107.0.0/16   OK
52.100.0.0/14   OK
104.47.0.0/17   OK
EOF

# master.cfにtbn-handlerを追加
sudo cat >> /etc/postfix/master.cf <<'EOF'

# TBN Secure Download - Mail handler
tbn-handler unix - n n - 10 pipe
  flags=DRXhu user=tbn-app
  argv=/opt/tbn-secure-download/venv/bin/python
  /opt/tbn-secure-download/mail_handler/postfix_handler.py
EOF

# Postfix再起動
sudo systemctl enable postfix
sudo systemctl restart postfix
```

### Step 6: 2台目VPS（冗長化）

#### lsyncd（ファイル双方向同期）

**両VPSで実施:**

```bash
# SSH鍵生成（tbn-appユーザーで）
sudo -u tbn-app ssh-keygen -t ed25519 -f /home/tbn-app/.ssh/id_ed25519 -N ""

# 相手VPSにSSH公開鍵を登録
# VPS1の公開鍵をVPS2に、VPS2の公開鍵をVPS1に登録
sudo -u tbn-app ssh-copy-id -i /home/tbn-app/.ssh/id_ed25519.pub tbn-app@<PEER_PRIVATE_IP>

# lsyncd設定
sudo cp deploy/lsyncd/lsyncd.conf.lua /etc/lsyncd/lsyncd.conf.lua
# ${PEER_PRIVATE_IP} を相手VPSのプライベートIPに書き換え
sudo sed -i "s/\${PEER_PRIVATE_IP}/<PEER_PRIVATE_IP>/" /etc/lsyncd/lsyncd.conf.lua

# ログディレクトリ
sudo mkdir -p /var/log/lsyncd

# lsyncd起動
sudo systemctl enable lsyncd
sudo systemctl start lsyncd
```

#### 同期確認

```bash
# VPS1でテストファイルを作成
sudo -u tbn-app touch /var/tbn-secure-download/files/sync_test

# VPS2で確認（数秒以内に反映される）
ls -la /var/tbn-secure-download/files/sync_test

# テストファイル削除
sudo -u tbn-app rm /var/tbn-secure-download/files/sync_test
```

### Step 7: Exchange Online設定

#### SMTPコネクタの作成

1. [Exchange管理センター](https://admin.exchange.microsoft.com/) にアクセス
2. **メールフロー** > **コネクタ** > **コネクタの追加**
3. 接続元: **Office 365**
4. 接続先: **パートナー組織**
5. 名前: `TBN Secure Download`
6. メールのルーティング:
   - **スマートホスト経由** を選択
   - VPS1のグローバルIP と VPS2のグローバルIP を両方追加
7. セキュリティ: **TLS暗号化を常に使用** にチェック
8. 検証: コネクタをテスト

#### メールフロールールの作成

1. **メールフロー** > **ルール** > **ルールの追加**
2. ルール名: `セキュアダウンロード転送`
3. 条件:
   - **送信者が組織内のユーザー**
   - **受信者が組織外のユーザー**
   - **メッセージに添付ファイルが含まれている**
4. 例外（任意）:
   - 受信者のドメインが `除外ドメインリスト` に含まれる場合は除外
5. アクション:
   - **メッセージを次のコネクタにリダイレクト** → `TBN Secure Download`
6. 優先度: 適切に設定

### Step 8: Microsoft Entra ID設定

#### アプリ登録 1: Graph API用（メール送信）

1. [Azure Portal](https://portal.azure.com/) > **Microsoft Entra ID** > **アプリの登録** > **新規登録**
2. 名前: `TBN Secure Download - Graph API`
3. サポートされているアカウントの種類: **この組織のアカウントのみ**
4. **APIのアクセス許可**:
   - `Mail.Send` (アプリケーション)
5. **管理者の同意を付与**
6. **証明書とシークレット** > クライアントシークレットを作成
7. 値を `.env` の `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` に設定

#### アプリ登録 2: Web認証用（送信者・管理者画面）

1. **アプリの登録** > **新規登録**
2. 名前: `TBN Secure Download - Web`
3. リダイレクトURI: `https://download.tbnet.jp/auth/callback` (Web)
4. **APIのアクセス許可**:
   - `User.Read` (委任)
   - `GroupMember.Read.All` (委任) ← 管理者グループ判定用
5. **証明書とシークレット** > クライアントシークレットを作成
6. 値を `.env` の `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` に設定

#### 管理者グループの設定

1. **Entra ID** > **グループ** > **新しいグループ**
2. グループ名: `TBN Secure Download Admins`
3. メンバー: システム管理者を追加
4. グループのオブジェクトIDを `.env` の `ADMIN_GROUP_ID` に設定

### Step 9: 監視・セキュリティ設定

#### fail2ban

```bash
# フィルター定義
sudo cat > /etc/fail2ban/filter.d/tbn-auth.conf <<'EOF'
[Definition]
failregex = ^.*"POST /d/.*/verify HTTP/.*" (401|403) .* <HOST>
            ^.*"POST /d/.*/request-code HTTP/.*" (403|429) .* <HOST>
ignoreregex =
EOF

# jail設定
sudo cp deploy/fail2ban/tbn-auth.conf /etc/fail2ban/jail.d/

# fail2ban再起動
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
```

#### cronジョブ設定

```bash
sudo -u tbn-app crontab -e
```

以下を追加:

```cron
# 期限切れファイル・DB削除（毎日3:00）
0 3 * * * /opt/tbn-secure-download/venv/bin/python /opt/tbn-secure-download/scripts/cleanup_expired.py >> /var/log/tbn-secure-download/cleanup.log 2>&1

# DBバックアップ（毎日2:00）
0 2 * * * /opt/tbn-secure-download/venv/bin/python /opt/tbn-secure-download/scripts/db_backup.py >> /var/log/tbn-secure-download/backup.log 2>&1

# 相互ヘルスチェック（毎分）
* * * * * PEER_HEALTH_URL=http://<PEER_PRIVATE_IP>:8000/internal/health HOSTNAME=$(hostname) /opt/tbn-secure-download/venv/bin/python /opt/tbn-secure-download/scripts/health_check.py >> /var/log/tbn-secure-download/health.log 2>&1
```

#### Teams通知（任意）

Microsoft Teams の Incoming Webhook URLを `.env` の `TEAMS_WEBHOOK_URL` に設定すると、ヘルスチェック異常時にTeamsに通知が送信されます。

---

## ローカル開発環境

### セットアップ

```bash
# リポジトリクローン
git clone https://github.com/masaspc/PPAPMails.git
cd PPAPMails

# Python仮想環境
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 環境変数（開発用）
cp .env.example .env
# .env を編集:
#   APP_ENV=development
#   APP_DEBUG=true
#   DATABASE_URL=postgresql+asyncpg://tbn_app:password@localhost:5432/tbn_secure_download
#   ENCRYPTION_KEY=<Fernet鍵を生成>
#   STORAGE_PATH=./uploaded_files
```

### ローカルDB作成

```bash
# PostgreSQLにDBとユーザーを作成
sudo -u postgres createuser tbn_app
sudo -u postgres createdb -O tbn_app tbn_secure_download

# マイグレーション実行
alembic -c migrations/alembic.ini upgrade head
```

### 開発サーバー起動

```bash
# FastAPI開発サーバー（ホットリロード付き）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ブラウザでアクセス
# http://localhost:8000/docs  ← API ドキュメント（デバッグモード時のみ）
```

### テスト実行

```bash
# 全テスト
pytest

# カバレッジ付き
pytest --cov=app --cov-report=html

# 特定テスト
pytest tests/test_file_manager.py -v
```

### コード品質チェック

```bash
# リンター
ruff check app/ tests/

# フォーマッター
ruff format app/ tests/

# 型チェック
mypy app/
```

---

## API リファレンス

### ダウンロードポータル（受信者向け）

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/d/{download_token}` | ダウンロードページ表示 |
| `POST` | `/d/{download_token}/request-code` | 認証コードリクエスト |
| `POST` | `/d/{download_token}/verify` | 認証コード検証 |
| `GET` | `/d/{download_token}/download/{attachment_id}` | ファイルダウンロード |

#### 認証コードリクエスト

```
POST /d/{download_token}/request-code
Content-Type: application/json

{"email": "recipient@example.com"}
```

レスポンス:
```json
{"message": "recipient@example.com に認証コードを送信しました"}
```

#### 認証コード検証

```
POST /d/{download_token}/verify
Content-Type: application/json

{"email": "recipient@example.com", "code": "123456"}
```

レスポンス:
```json
{"success": true, "message": "認証に成功しました。", "session_token": "..."}
```

### 送信者向け（Entra ID認証必須）

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/sender/` | 送信履歴一覧 |
| `GET` | `/sender/transfer/{id}` | 送信詳細（DL状況） |
| `POST` | `/sender/transfer/{id}/revoke` | URL無効化 |

### 管理者向け（Entra ID + 管理者グループ必須）

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/admin/` | ダッシュボード |
| `GET` | `/admin/transfers` | 全社送信履歴 |
| `GET` | `/admin/transfers/{id}` | 送信詳細 |
| `GET` | `/admin/settings` | システム設定画面 |
| `PUT` | `/admin/settings` | システム設定変更 |
| `GET` | `/admin/excluded-domains` | 除外ドメイン管理 |
| `POST` | `/admin/excluded-domains` | 除外ドメイン追加 |
| `DELETE` | `/admin/excluded-domains/{id}` | 除外ドメイン削除 |
| `GET` | `/admin/audit-logs` | 監査ログ閲覧 |
| `GET` | `/admin/audit-logs/export` | 監査ログCSV出力 |

### 内部API

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/internal/process-email` | メール処理トリガー |
| `GET` | `/internal/health` | ヘルスチェック |

---

## 運用手順

### ゼロダウンタイムアップデート

ローリングアップデートで1台ずつ更新します。

```bash
# === VPS2を先に更新 ===

# 1. VPS2をLBから切り離し（ConoHaパネルまたはヘルスチェック失敗で自動）

# 2. VPS2でアップデート実施
cd /opt/tbn-secure-download
sudo -u tbn-app git pull origin main
sudo -u tbn-app ./venv/bin/pip install -r requirements.txt
sudo systemctl restart tbn-secure-download

# 3. VPS2の動作確認
curl http://127.0.0.1:8000/internal/health

# 4. VPS2をLBに復帰

# === VPS1を更新 ===

# 5. VPS1をLBから切り離し

# 6. VPS1でアップデート実施（同じ手順）
cd /opt/tbn-secure-download
sudo -u tbn-app git pull origin main
sudo -u tbn-app ./venv/bin/pip install -r requirements.txt

# 7. DBマイグレーション（必要な場合、VPS1でのみ実行）
sudo -u tbn-app ./venv/bin/alembic -c migrations/alembic.ini upgrade head

sudo systemctl restart tbn-secure-download

# 8. VPS1の動作確認
curl http://127.0.0.1:8000/internal/health

# 9. VPS1をLBに復帰
```

### DBフェイルオーバー

VPS1（Primary）が障害でダウンした場合:

```bash
# VPS2で実行

# 1. StandbyをPrimaryに昇格
sudo -u postgres pg_ctl promote -D /var/lib/postgresql/16/main

# 2. アプリケーション再起動（localhostのDBに接続するため変更不要）
sudo systemctl restart tbn-secure-download

# 3. 動作確認
curl http://127.0.0.1:8000/internal/health
```

VPS1が復旧した場合:

```bash
# VPS1をStandbyとして再構築

# 1. PostgreSQL停止
sudo systemctl stop postgresql

# 2. データディレクトリをクリア
sudo rm -rf /var/lib/postgresql/16/main/*

# 3. VPS2（新Primary）からベースバックアップ
sudo -u postgres pg_basebackup \
    -h <VPS2_PRIVATE_IP> \
    -U replicator \
    -D /var/lib/postgresql/16/main \
    -P -R

# 4. Standby設定を適用
sudo cp deploy/postgresql/standby.conf /etc/postgresql/16/main/conf.d/tbn-replication.conf

# 5. PostgreSQL起動
sudo systemctl start postgresql
```

### バックアップとリストア

#### 自動バックアップ

- cronで毎日2:00に `scripts/db_backup.py` が実行
- バックアップ先: `/var/tbn-secure-download/backups/`
- 保持期間: 30日（古いバックアップは自動削除）
- ConoHa自動バックアップも併用

#### 手動バックアップ

```bash
sudo -u tbn-app /opt/tbn-secure-download/venv/bin/python \
    /opt/tbn-secure-download/scripts/db_backup.py
```

#### リストア

```bash
# バックアップファイルからリストア
gunzip -c /var/tbn-secure-download/backups/tbn_secure_download_YYYYMMDD_HHMMSS.sql.gz \
    | sudo -u postgres psql tbn_secure_download
```

### 定期メンテナンス

| タスク | 頻度 | 方法 |
|--------|------|------|
| 期限切れファイル削除 | 毎日3:00 (自動) | `scripts/cleanup_expired.py` |
| DBバックアップ | 毎日2:00 (自動) | `scripts/db_backup.py` |
| 相互ヘルスチェック | 毎分 (自動) | `scripts/health_check.py` |
| SSL証明書更新 | 90日ごと (自動) | certbot + renewal-hook |
| OSアップデート | 随時 (自動) | unattended-upgrades |
| ログローテーション | 必要に応じて | logrotate設定追加 |

---

## トラブルシューティング

### メールが処理されない

```bash
# Postfixキュー確認
sudo postqueue -p

# Postfixログ確認
sudo tail -f /var/log/mail.log

# メールハンドラーログ確認
sudo tail -f /var/log/tbn-secure-download/mail_handler.log

# FastAPIログ確認
sudo journalctl -u tbn-secure-download -f
```

### ダウンロードできない

```bash
# ファイルの存在確認
ls -la /var/tbn-secure-download/files/

# lsyncd同期状態確認
sudo cat /var/log/lsyncd/lsyncd.status

# アプリケーションログ
sudo tail -f /var/log/tbn-secure-download/error.log
```

### DB接続エラー

```bash
# PostgreSQL状態確認
sudo systemctl status postgresql

# レプリケーション状態確認（Primary側）
sudo -u postgres psql -c "SELECT * FROM pg_stat_replication;"

# DB接続テスト
sudo -u tbn-app psql -h 127.0.0.1 -U tbn_app -d tbn_secure_download -c "SELECT 1;"
```

### fail2banでIPがブロックされた

```bash
# ブロック状態確認
sudo fail2ban-client status tbn-auth

# 特定IPのブロック解除
sudo fail2ban-client set tbn-auth unbanip <IP_ADDRESS>
```

### Graph API メール送信エラー

```bash
# トークン取得テスト
sudo -u tbn-app /opt/tbn-secure-download/venv/bin/python -c "
from app.services.graph_api import GraphAPIClient
import asyncio
client = GraphAPIClient()
token = asyncio.run(client._get_access_token())
print('Token acquired:', token[:20] + '...')
"
```

---

## データベース設計

### ER図（テーブル関連）

```
transfers ─┬── recipients (1:N)
            ├── attachments (1:N) ── download_logs (1:N)
            ├── auth_codes (1:N)
            └── auth_sessions (1:N)

system_settings (独立)
excluded_domains (独立)
audit_logs (独立)
```

### テーブル一覧

| テーブル | 説明 | レコード数目安 |
|---------|------|-------------|
| `transfers` | 送信履歴 | 月数百件 |
| `recipients` | 受信者 | transfers × 1〜10 |
| `attachments` | 添付ファイル | transfers × 1〜5 |
| `auth_codes` | 認証コード（一時的） | DLアクセスごと |
| `auth_sessions` | 認証セッション | 認証成功ごと |
| `download_logs` | DLログ | attachments × 1〜10 |
| `system_settings` | システム設定 | 9件（固定） |
| `excluded_domains` | 除外ドメイン | 数件〜数十件 |
| `audit_logs` | 監査ログ | 管理操作ごと |

---

## セキュリティ

| 対策 | 実装 |
|------|------|
| ファイル暗号化 | AES-256 (Fernet) で保管時暗号化 |
| 通信暗号化 | HTTPS必須 (TLS 1.2+, Let's Encrypt) |
| 認証コード | 6桁ワンタイム、10分有効、5回失敗でロック |
| URL推測防止 | UUID v4 ベース（122ビットランダム） |
| ブルートフォース対策 | fail2ban + IPレート制限 (30回/分) |
| ファイアウォール | UFW (80/443/25/SSH のみ) |
| セッション管理 | HttpOnly + Secure Cookie, DB保存 |
| 秘匿情報管理 | 暗号化キー・認証情報は環境変数 (.env) |
| 監査ログ | 全管理操作を記録、CSV出力可能 |
| HTTPヘッダー | HSTS, X-Content-Type-Options, X-Frame-Options, CSP |
| systemd保護 | NoNewPrivileges, ProtectSystem=strict, PrivateTmp |

---

## コスト

### 月額ランニングコスト

| 項目 | 単価 | 数量 | 月額 |
|------|------|------|------|
| ConoHa VPS 2GBプラン（12ヶ月契約） | 約575円 | 2台 | 約1,150円 |
| ConoHa ロードバランサー | 約1,210円 | 1 | 約1,210円 |
| プライベートネットワーク | 0円 | 1 | 0円 |
| 自動バックアップ | 約363円 | 1 | 約363円 |
| 独自ドメイン | 約100円 | 1 | 約100円 |
| SSL証明書 (Let's Encrypt) | 0円 | - | 0円 |
| **合計** | | | **約2,823円/月** |

### 年間コスト比較

| 構成 | 年間コスト |
|------|-----------|
| HENNGE One DLP | 約412,800円 |
| **本システム（ConoHa VPS冗長構成）** | **約33,876円** |
| 差額（年間削減額） | **-378,924円** |

---

## ライセンス

Proprietary - 東京ベイネットワーク株式会社
