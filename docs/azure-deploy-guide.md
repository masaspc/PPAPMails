# Azure デプロイ完全ガイド（初心者向け）

Secure Download システムを Azure 上にゼロからデプロイする手順です。
Azure をあまり使ったことがない方でも進められるよう、画面操作とコマンドの両方を記載しています。

## 全体の流れ

```
Step 0: 事前準備（ツールのインストール）
  |
Step 1: Azure アカウント・サブスクリプションの準備
  |
Step 2: Microsoft Entra ID でアプリ登録（2件）
  |
Step 3: Exchange Online で処理用メールボックス作成
  |
Step 4: 秘密鍵・パスワードの生成
  |
Step 5: Azure リソースの一括デプロイ（Bicep）
  |
Step 6: データベースのマイグレーション
  |
Step 7: App Service にアプリをデプロイ
  |
Step 8: Azure Functions にメール処理をデプロイ
  |
Step 9: Exchange Online のメールフロールール設定
  |
Step 10: カスタムドメイン・SSL 設定
  |
Step 11: 動作確認
```

---

## Step 0: 事前準備（ローカルPCにツールをインストール）

### 0-1. Azure CLI のインストール

Azure をコマンドラインで操作するためのツールです。

**Windows:**
```powershell
# winget を使う場合
winget install -e --id Microsoft.AzureCLI

# または MSI インストーラーをダウンロード
# https://learn.microsoft.com/ja-jp/cli/azure/install-azure-cli-windows
```

**macOS:**
```bash
brew install azure-cli
```

**Linux (Ubuntu/Debian):**
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

インストール確認:
```bash
az version
# azure-cli  2.xx.x が表示されれば OK
```

### 0-2. Azure Functions Core Tools のインストール

Azure Functions をローカルから操作するためのツールです。

**Windows:**
```powershell
winget install -e --id Microsoft.Azure.FunctionsCoreTools
```

**macOS:**
```bash
brew tap azure/functions
brew install azure-functions-core-tools@4
```

**Linux:**
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
sudo mv microsoft.gpg /etc/apt/trusted.gpg.d/microsoft.gpg
sudo sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/microsoft-ubuntu-$(lsb_release -cs)-prod $(lsb_release -cs) main" > /etc/apt/sources.list.d/dotnetdev.list'
sudo apt-get update
sudo apt-get install azure-functions-core-tools-4
```

インストール確認:
```bash
func --version
# 4.x.x が表示されれば OK
```

### 0-3. Python 3.12 のインストール

```bash
python3 --version
# Python 3.12.x が必要
```

### 0-4. Git のインストール確認

```bash
git --version
```

---

## Step 1: Azure アカウント・サブスクリプションの準備

### 1-1. Azure アカウント作成（まだない場合）

1. https://azure.microsoft.com/ja-jp/free/ にアクセス
2. 「無料で始める」をクリック
3. Microsoft アカウントでサインイン（または新規作成）
4. クレジットカード登録（無料枠あり、最初の30日間は200ドル分のクレジット付き）

### 1-2. Azure CLI でログイン

```bash
az login
```

ブラウザが開くので、Azure アカウントでログインします。
ログイン後、ターミナルにサブスクリプション一覧が表示されます。

```bash
# サブスクリプションの確認
az account show --output table

# 複数サブスクリプションがある場合、使いたいものを選択
az account set --subscription "<サブスクリプション名 or ID>"
```

### 1-3. リソースグループの作成

リソースグループは Azure リソースをまとめる「フォルダ」のようなものです。

```bash
az group create \
    --name rg-secure-download \
    --location japaneast

# 確認
az group show --name rg-secure-download --output table
```

> `japaneast` は東日本リージョンです。西日本にしたい場合は `japanwest` を指定します。

---

## Step 2: Microsoft Entra ID でアプリ登録

Azure Portal（https://portal.azure.com）にログインして操作します。

### 2-1. テナントID の確認

1. Azure Portal 上部の検索バーに「Microsoft Entra ID」と入力
2. 「概要」ページの「テナントID」をメモ → **これが `AZURE_TENANT_ID`**

### 2-2. アプリ登録 1: Graph API用（メール送信・読み取り）

このアプリは、システムが Graph API 経由でメールを送信・読み取りするために使います。

1. Azure Portal > **Microsoft Entra ID** > 左メニュー **アプリの登録**
2. **「+ 新規登録」** をクリック
3. 以下を入力:
   - 名前: `Secure Download - Graph API`
   - サポートされているアカウントの種類: **この組織ディレクトリのみ...**
   - リダイレクト URI: **設定しない（空白のまま）**
4. **「登録」** をクリック

#### クライアントID のメモ

登録後に表示される画面で:
- **アプリケーション (クライアント) ID** をメモ → **`AZURE_CLIENT_ID`**

#### API のアクセス許可を追加

1. 左メニュー **「API のアクセス許可」**
2. **「+ アクセス許可の追加」** をクリック
3. **「Microsoft Graph」** を選択
4. **「アプリケーションの許可」** を選択（「委任された許可」ではない！）
5. 検索して以下を追加:
   - `Mail.Send` — メール送信用
   - `Mail.Read` — 処理用メールボックスの読み取り用
   - `Mail.ReadWrite` — 処理済みメールを既読にマーク用
6. **「アクセス許可の追加」** をクリック
7. **「<テナント名>に管理者の同意を与えます」** ボタンをクリック → **「はい」**

> 「管理者の同意を与えます」が灰色で押せない場合は、全体管理者権限を持つアカウントでログインしてください。

#### クライアントシークレットの作成

1. 左メニュー **「証明書とシークレット」**
2. **「+ 新しいクライアント シークレット」** をクリック
3. 説明: `Production` 、有効期限: `24 か月` を選択
4. **「追加」** をクリック
5. 表示された **「値」** をメモ → **`AZURE_CLIENT_SECRET`**

> この値は画面を離れると二度と表示されません。必ずこの時点でメモしてください。

### 2-3. アプリ登録 2: Web認証用（送信者・管理者画面ログイン）

1. Azure Portal > **Microsoft Entra ID** > **アプリの登録** > **「+ 新規登録」**
2. 以下を入力:
   - 名前: `Secure Download - Web`
   - サポートされているアカウントの種類: **この組織ディレクトリのみ...**
   - リダイレクトURI: **Web** を選択し、`https://download.example.com/auth/callback` を入力
     （`download.example.com` は実際に使うドメインに置き換える）
3. **「登録」** をクリック

#### クライアントID のメモ

- **アプリケーション (クライアント) ID** をメモ → **`ENTRA_CLIENT_ID`**

#### API のアクセス許可を追加

1. **「API のアクセス許可」** > **「+ アクセス許可の追加」**
2. **「Microsoft Graph」** > **「委任されたアクセス許可」** を選択（今度は「委任」）
3. 以下を追加:
   - `User.Read` — ユーザー情報取得
   - `GroupMember.Read.All` — 管理者グループ判定用
4. **「管理者の同意を与えます」** をクリック

#### クライアントシークレットの作成

1. **「証明書とシークレット」** > **「+ 新しいクライアント シークレット」**
2. 追加して **「値」** をメモ → **`ENTRA_CLIENT_SECRET`**

### 2-4. 管理者グループの作成

1. Azure Portal > **Microsoft Entra ID** > **グループ** > **「+ 新しいグループ」**
2. 以下を入力:
   - グループの種類: **セキュリティ**
   - グループ名: `Secure Download Admins`
   - メンバー: 管理画面にアクセスできるユーザーを追加
3. **「作成」** をクリック
4. 作成されたグループをクリックし、**「オブジェクト ID」** をメモ → **`ADMIN_GROUP_ID`**

---

## Step 3: Exchange Online で処理用メールボックス作成

Azure Functions がポーリングするためのメールボックスを作成します。

### 3-1. 共有メールボックスの作成

1. [Exchange 管理センター](https://admin.exchange.microsoft.com/) にアクセス
2. 左メニュー **「受信者」** > **「共有メールボックス」**
3. **「+ 共有メールボックスの追加」** をクリック
4. 以下を入力:
   - 表示名: `Secure Download Processing`
   - メールアドレス: `process@example.com`（実際のドメインに置き換え）
5. **「変更を保存」** をクリック

このメールアドレス → **`PROCESSING_MAILBOX`** としてメモ

### 3-2. Graph API 用アプリにメールボックスアクセス権を付与

PowerShell で Exchange Online に接続して、Graph API アプリが処理用メールボックスにのみアクセスできるよう制限します（推奨）。

```powershell
# Exchange Online PowerShell モジュールのインストール（初回のみ）
Install-Module -Name ExchangeOnlineManagement

# 接続
Connect-ExchangeOnline

# アプリケーションアクセスポリシーの作成
# AZURE_CLIENT_ID を実際の値に置き換え
New-ApplicationAccessPolicy `
    -AppId "<AZURE_CLIENT_ID>" `
    -PolicyScopeGroupId "process@example.com" `
    -AccessRight RestrictAccess `
    -Description "Secure Download - Graph API access"

# 確認
Get-ApplicationAccessPolicy | Format-List
```

> これを設定すると、Graph API アプリは `process@example.com` のメールしか読めなくなります（セキュリティ上推奨）。

---

## Step 4: 秘密鍵・パスワードの生成

デプロイに必要な秘密情報を生成します。

```bash
# Python がインストール済みであることを確認
python3 --version

# 1. APP_SECRET_KEY（セッション暗号化用）
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
# → 長いランダム文字列が出力される（メモする）

# 2. ENCRYPTION_KEY（ファイル暗号化用 Fernet キー）
pip install cryptography  # 未インストールの場合
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → Base64文字列が出力される（メモする）

# 3. PostgreSQL 管理者パスワード
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# → ランダム文字列が出力される（メモする）
```

ここまでで以下の値が揃っているはずです:

| 変数名 | 取得元 |
|--------|--------|
| `AZURE_TENANT_ID` | Step 2-1 で確認 |
| `AZURE_CLIENT_ID` | Step 2-2 で取得 |
| `AZURE_CLIENT_SECRET` | Step 2-2 で取得 |
| `ENTRA_CLIENT_ID` | Step 2-3 で取得 |
| `ENTRA_CLIENT_SECRET` | Step 2-3 で取得 |
| `ADMIN_GROUP_ID` | Step 2-4 で取得 |
| `PROCESSING_MAILBOX` | Step 3 で作成 |
| `APP_SECRET_KEY` | Step 4 で生成 |
| `ENCRYPTION_KEY` | Step 4 で生成 |
| PostgreSQL パスワード | Step 4 で生成 |


---

## Step 5: Azure リソースの一括デプロイ（Bicep）

Bicep テンプレートを使って、必要な Azure リソースをまとめて作成します。

### 5-1. リポジトリのクローン

```bash
git clone https://github.com/masaspc/PPAPMails.git
cd PPAPMails
```

### 5-2. パラメータファイルの作成

```bash
cp deploy/azure/parameters.example.json deploy/azure/parameters.json
```

`deploy/azure/parameters.json` をテキストエディタで開き、Step 2〜4 で取得した値を設定します:

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "environment": {
      "value": "prod"
    },
    "namePrefix": {
      "value": "sd"
    },
    "postgresAdminUser": {
      "value": "pgadmin"
    },
    "postgresAdminPassword": {
      "value": "ここにStep4で生成したPostgreSQLパスワード"
    },
    "appSecretKey": {
      "value": "ここにStep4で生成したAPP_SECRET_KEY"
    },
    "encryptionKey": {
      "value": "ここにStep4で生成したENCRYPTION_KEY"
    },
    "azureTenantId": {
      "value": "ここにStep2-1のテナントID"
    },
    "azureClientId": {
      "value": "ここにStep2-2のクライアントID"
    },
    "azureClientSecret": {
      "value": "ここにStep2-2のクライアントシークレット"
    },
    "entraClientId": {
      "value": "ここにStep2-3のクライアントID"
    },
    "entraClientSecret": {
      "value": "ここにStep2-3のクライアントシークレット"
    },
    "graphSenderEmail": {
      "value": "noreply@yourdomain.com"
    },
    "portalDomain": {
      "value": "download.yourdomain.com"
    },
    "adminGroupId": {
      "value": "ここにStep2-4のグループObject ID"
    },
    "processingMailbox": {
      "value": "process@yourdomain.com"
    }
  }
}
```

> **注意**: `graphSenderEmail` は組織のメールアドレスである必要があります。Graph API で送信するため、組織の Exchange Online に存在するアドレス（共有メールボックスでも可）を指定してください。

### 5-3. Bicep テンプレートの実行

```bash
az deployment group create \
    --resource-group rg-secure-download \
    --template-file deploy/azure/main.bicep \
    --parameters deploy/azure/parameters.json \
    --verbose
```

実行には 5〜15分 かかります。以下のリソースが自動的に作成されます:

| リソース | 説明 |
|----------|------|
| Log Analytics ワークスペース | ログ収集基盤 |
| Application Insights | アプリケーション監視 |
| Storage Account | Blob Storage + Functions用ストレージ |
| PostgreSQL Flexible Server | データベースサーバー |
| App Service Plan | Web/Functions の実行基盤 |
| App Service | FastAPI Webアプリケーション |
| Function App | メール処理・定期タスク |

### 5-4. デプロイ結果の確認

```bash
# デプロイ結果を表示
az deployment group show \
    --resource-group rg-secure-download \
    --name main \
    --query properties.outputs \
    --output table
```

出力例:
```
Name                              Type    Value
--------------------------------  ------  ----------------------------------------
appServiceUrl                     String  https://app-sd-prod.azurewebsites.net
functionAppUrl                    String  https://func-sd-prod.azurewebsites.net
postgresHost                      String  psql-sd-prod.postgres.database.azure.com
storageAccountName                String  stsdprod
appInsightsInstrumentationKey     String  xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

これらの値をメモしてください。

### トラブルシューティング: デプロイが失敗した場合

```bash
# エラー詳細を確認
az deployment group show \
    --resource-group rg-secure-download \
    --name main \
    --query properties.error

# やり直す場合（リソースグループごと削除して最初から）
az group delete --name rg-secure-download --yes --no-wait
# 数分待ってから再度 az group create からやり直し
```

---

## Step 6: データベースのマイグレーション

テーブルを作成します。

### 6-1. ローカルPCからの接続許可

Azure PostgreSQL はデフォルトで外部からのアクセスを拒否しています。
ローカルPCから接続するために、一時的にファイアウォールルールを追加します。

```bash
# 自分のグローバルIPアドレスを確認
curl -s https://ifconfig.me
# → 例: 203.0.113.50

# ファイアウォールルールを追加
az postgres flexible-server firewall-rule create \
    --resource-group rg-secure-download \
    --name psql-sd-prod \
    --rule-name AllowMyIP \
    --start-ip-address 203.0.113.50 \
    --end-ip-address 203.0.113.50
```

### 6-2. Python 仮想環境のセットアップ

```bash
cd PPAPMails

# 仮想環境の作成
python3.12 -m venv venv

# 仮想環境を有効化
# Linux/macOS:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# 依存パッケージのインストール
pip install -r requirements.txt
```

### 6-3. マイグレーション実行

```bash
# DATABASE_URL_SYNC を設定
# <password> と <host> をStep 4, 5 の値に置き換え
export DATABASE_URL_SYNC="postgresql://pgadmin:<password>@psql-sd-prod.postgres.database.azure.com:5432/secure_download?sslmode=require"

# マイグレーション実行
alembic -c migrations/alembic.ini upgrade head
```

成功すると以下のような出力が表示されます:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 001, initial
```

### 6-4. ファイアウォールルールの削除（セキュリティ上推奨）

マイグレーション完了後、一時的に追加したファイアウォールルールを削除します。

```bash
az postgres flexible-server firewall-rule delete \
    --resource-group rg-secure-download \
    --name psql-sd-prod \
    --rule-name AllowMyIP \
    --yes
```

---

## Step 7: App Service にアプリをデプロイ

### 7-1. デプロイ用 ZIP ファイルの作成

```bash
cd PPAPMails

# 必要なファイルを ZIP にまとめる
zip -r app.zip \
    app/ \
    migrations/ \
    requirements.txt \
    pyproject.toml \
    -x "**/__pycache__/*" "**/.pytest_cache/*"
```

### 7-2. App Service へのデプロイ

```bash
az webapp deploy \
    --resource-group rg-secure-download \
    --name app-sd-prod \
    --src-path app.zip \
    --type zip
```

初回デプロイは 3〜5分 かかります（Azure が Python パッケージをインストールするため）。

### 7-3. デプロイ状況の確認

```bash
# ログをリアルタイムで確認
az webapp log tail \
    --resource-group rg-secure-download \
    --name app-sd-prod

# Ctrl+C で停止
```

### 7-4. 動作確認

```bash
curl https://app-sd-prod.azurewebsites.net/internal/health
```

正常な応答:
```json
{"status":"ok","database":"ok","storage":"ok"}
```

ブラウザで `https://app-sd-prod.azurewebsites.net` にアクセスしてみてください。
ログインページが表示されれば成功です。

---

## Step 8: Azure Functions にメール処理をデプロイ

### 8-1. Azure Functions Core Tools でデプロイ

```bash
cd PPAPMails/azure_functions

# デプロイ
func azure functionapp publish func-sd-prod --python
```

初回は 3〜5分 かかります。

### 8-2. Functions の動作確認

```bash
# ヘルスチェック
curl https://func-sd-prod.azurewebsites.net/api/health
```

### 8-3. Functions のログ確認

```bash
# リアルタイムログ
az webapp log tail \
    --resource-group rg-secure-download \
    --name func-sd-prod
```

Azure Portal でも確認できます:
1. Azure Portal > **関数アプリ** > `func-sd-prod`
2. 左メニュー **「監視」** > **「ログ ストリーム」**

---

## Step 9: Exchange Online のメールフロールール設定

社外宛ての添付ファイル付きメールを処理用メールボックスにリダイレクトするルールを作成します。

### 9-1. Exchange 管理センターにアクセス

1. https://admin.exchange.microsoft.com/ にアクセス
2. 全体管理者アカウントでログイン

### 9-2. メールフロールールの作成

1. 左メニュー **「メール フロー」** > **「ルール」**
2. **「+ ルールを追加」** > **「新しいルールの作成」**
3. 以下を設定:

| 項目 | 設定値 |
|------|--------|
| 名前 | `セキュアダウンロード転送` |
| このルールを適用する条件 | **送信者が組織内のユーザー** |
| および | **受信者が組織外のユーザー** |
| および | **メッセージに添付ファイルが含まれている** |
| 実行する処理 | **メッセージを次のアドレスにリダイレクト** → `process@yourdomain.com` |
| 優先度 | 0（最優先） |
| モード | **強制** |

4. **「保存」** をクリック

> **重要**: ルールの「モード」が「強制」になっていることを確認してください。「テスト」モードではメールがリダイレクトされません。

### 9-3. テスト送信

1. 組織内のユーザーから、組織外のメールアドレス（例: 個人のGmail）に、何かファイルを添付してテストメールを送信
2. Azure Functions のログで処理されたことを確認:
   ```bash
   az webapp log tail --resource-group rg-secure-download --name func-sd-prod
   ```
3. 受信者にダウンロードリンク付きのメールが届くことを確認

---

## Step 10: カスタムドメイン・SSL 設定

`app-sd-prod.azurewebsites.net` の代わりに `download.yourdomain.com` でアクセスできるようにします。

### 10-1. DNS 設定（ドメイン管理画面で実施）

お使いのドメインの DNS 管理画面（お名前.com、Cloudflare、Route 53 など）で以下のレコードを追加:

| タイプ | ホスト名 | 値 |
|--------|----------|-----|
| CNAME | `download` | `app-sd-prod.azurewebsites.net` |
| TXT | `asuid.download` | (次の手順で取得する値) |

### 10-2. ドメイン検証用 TXT レコードの取得

```bash
az webapp config hostname get-external-dns \
    --resource-group rg-secure-download \
    --webapp-name app-sd-prod \
    --hostname download.yourdomain.com \
    --query "[?recordType=='TXT'].value" -o tsv
```

表示された値を DNS の TXT レコード (`asuid.download`) に設定してください。

### 10-3. カスタムドメインの追加

DNS の反映を待ってから（通常数分〜数時間）:

```bash
# カスタムドメインを追加
az webapp config hostname add \
    --resource-group rg-secure-download \
    --webapp-name app-sd-prod \
    --hostname download.yourdomain.com
```

### 10-4. SSL 証明書の設定（無料）

App Service Managed Certificate を使います（Let's Encrypt 相当の無料証明書）。

```bash
# マネージド証明書の作成
az webapp config ssl create \
    --resource-group rg-secure-download \
    --name app-sd-prod \
    --hostname download.yourdomain.com

# HTTPS のみにリダイレクト（HTTP アクセスを自動リダイレクト）
az webapp update \
    --resource-group rg-secure-download \
    --name app-sd-prod \
    --set httpsOnly=true
```

### 10-5. Entra ID のリダイレクト URI を更新

カスタムドメインを設定したら、Web認証用アプリのリダイレクトURIも更新します。

1. Azure Portal > **Microsoft Entra ID** > **アプリの登録** > `Secure Download - Web`
2. 左メニュー **「認証」**
3. リダイレクト URI を `https://download.yourdomain.com/auth/callback` に変更
4. **「保存」**

---

## Step 11: 動作確認チェックリスト

全てのステップが完了したら、以下を確認してください。

### ヘルスチェック

```bash
# App Service
curl https://download.yourdomain.com/internal/health
# → {"status":"ok","database":"ok","storage":"ok"}

# Azure Functions
curl https://func-sd-prod.azurewebsites.net/api/health
# → {"status":"ok","database":"ok","storage":"ok","version":"2.0.0"}
```

### Web 画面

- [ ] `https://download.yourdomain.com` にアクセスし、Entra ID ログイン画面にリダイレクトされる
- [ ] ログイン後、送信者ダッシュボードが表示される
- [ ] 管理者グループのユーザーでログインすると `/admin/` にアクセスできる

### メール処理

- [ ] 社外宛てに添付ファイル付きメールを送信する
- [ ] 30秒以内に Azure Functions がメールを処理する（ログで確認）
- [ ] 受信者にダウンロードリンク付きメールが届く
- [ ] リンクをクリックするとダウンロードページが表示される
- [ ] メールアドレスを入力すると認証コードが届く
- [ ] 認証コードを入力するとファイル一覧が表示される
- [ ] ファイルをダウンロードできる

---

## 参考: Azure Portal での確認方法

Azure Portal (https://portal.azure.com) で作成したリソースを確認できます。

### リソース一覧

1. Azure Portal 上部の検索バーに「rg-secure-download」と入力
2. リソースグループをクリック
3. 作成されたリソース一覧が表示されます

### よく使う画面

| 確認したいこと | Azure Portal での場所 |
|---------------|----------------------|
| App Service のログ | App Service > 監視 > ログ ストリーム |
| Functions のログ | 関数アプリ > 監視 > ログ ストリーム |
| DB の状態 | PostgreSQL > 概要 |
| Blob Storage の中身 | ストレージアカウント > コンテナー |
| Application Insights | Application Insights > 調査 > ログ |
| 全体のコスト | コストの管理と請求 > コスト分析 |

---

## 参考: 月額コスト内訳

| リソース | SKU | 月額概算 |
|----------|-----|---------|
| App Service Plan (B1) | 1 コア, 1.75 GB RAM | 約1,900円 |
| PostgreSQL (B1ms) | 1 vCore, 2 GB RAM, 32 GB | 約2,500円 |
| Storage Account | LRS, 数GB想定 | 約100円 |
| Azure Functions | Consumption (無料枠内) | 約0円 |
| Application Insights | 少量データ | 約100円 |
| **合計** | | **約4,600円/月** |

> 最初の30日間は Azure 無料クレジット（200ドル）が使えるので、テスト期間は実質無料です。
