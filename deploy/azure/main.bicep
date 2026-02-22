// Secure Download - Azure インフラストラクチャ定義
//
// デプロイ:
//   az deployment group create \
//     --resource-group rg-secure-download \
//     --template-file deploy/azure/main.bicep \
//     --parameters deploy/azure/parameters.json

@description('リソースのデプロイ先リージョン')
param location string = resourceGroup().location

@description('環境名 (prod, staging, dev)')
@allowed(['prod', 'staging', 'dev'])
param environment string = 'prod'

@description('リソース名のプレフィックス')
param namePrefix string = 'sd'

@description('PostgreSQL 管理者ユーザー名')
param postgresAdminUser string = 'pgadmin'

@description('PostgreSQL 管理者パスワード')
@secure()
param postgresAdminPassword string

@description('アプリケーション シークレットキー')
@secure()
param appSecretKey string

@description('ファイル暗号化キー (Fernet)')
@secure()
param encryptionKey string

@description('Azure AD テナントID')
param azureTenantId string

@description('Graph API アプリケーション クライアントID')
param azureClientId string

@description('Graph API クライアントシークレット')
@secure()
param azureClientSecret string

@description('Entra ID Web認証 クライアントID')
param entraClientId string

@description('Entra ID Web認証 クライアントシークレット')
@secure()
param entraClientSecret string

@description('Graph API メール送信元アドレス')
param graphSenderEmail string = 'noreply@example.com'

@description('ポータルドメイン名')
param portalDomain string = 'download.example.com'

@description('管理者グループのObject ID')
param adminGroupId string = ''

@description('処理用メールボックス')
param processingMailbox string = ''

// --- 名前の生成 ---
var suffix = '${namePrefix}-${environment}'
var appServicePlanName = 'asp-${suffix}'
var appServiceName = 'app-${suffix}'
var functionAppName = 'func-${suffix}'
var storageAccountName = replace('st${namePrefix}${environment}', '-', '')
var postgresServerName = 'psql-${suffix}'
var logAnalyticsName = 'log-${suffix}'
var appInsightsName = 'appi-${suffix}'
var frontDoorName = 'fd-${suffix}'

// --- Log Analytics ワークスペース ---
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// --- Application Insights ---
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// --- Storage Account (Blob Storage + Functions用) ---
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource downloadContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'secure-downloads'
  properties: {
    publicAccess: 'None'
  }
}

// --- PostgreSQL Flexible Server ---
resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: postgresServerName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
  }
}

resource postgresFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-12-01-preview' = {
  parent: postgresServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-12-01-preview' = {
  parent: postgresServer
  name: 'secure_download'
  properties: {
    charset: 'UTF8'
    collation: 'ja_JP.utf8'
  }
}

// --- App Service Plan (Web App + Functions 共用) ---
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

// --- App Service (FastAPI Web App) ---
resource appService 'Microsoft.Web/sites@2023-12-01' = {
  name: appServiceName
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      ftpsState: 'Disabled'
      appCommandLine: 'gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000'
      appSettings: [
        { name: 'APP_ENV', value: environment }
        { name: 'APP_SECRET_KEY', value: appSecretKey }
        { name: 'APP_DEBUG', value: 'false' }
        { name: 'PORTAL_DOMAIN', value: portalDomain }
        { name: 'DATABASE_URL', value: 'postgresql+asyncpg://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/secure_download?ssl=require' }
        { name: 'DATABASE_URL_SYNC', value: 'postgresql://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/secure_download?sslmode=require' }
        { name: 'STORAGE_BACKEND', value: 'azure_blob' }
        { name: 'ENCRYPTION_KEY', value: encryptionKey }
        { name: 'AZURE_STORAGE_CONNECTION_STRING', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net' }
        { name: 'AZURE_STORAGE_CONTAINER_NAME', value: 'secure-downloads' }
        { name: 'AZURE_TENANT_ID', value: azureTenantId }
        { name: 'AZURE_CLIENT_ID', value: azureClientId }
        { name: 'AZURE_CLIENT_SECRET', value: azureClientSecret }
        { name: 'GRAPH_SENDER_EMAIL', value: graphSenderEmail }
        { name: 'ENTRA_CLIENT_ID', value: entraClientId }
        { name: 'ENTRA_CLIENT_SECRET', value: entraClientSecret }
        { name: 'ENTRA_REDIRECT_URI', value: 'https://${portalDomain}/auth/callback' }
        { name: 'ADMIN_GROUP_ID', value: adminGroupId }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'WEBSITES_PORT', value: '8000' }
      ]
    }
  }
}

// --- Function App (メール処理 + 定期タスク) ---
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'APP_ENV', value: environment }
        { name: 'APP_SECRET_KEY', value: appSecretKey }
        { name: 'DATABASE_URL', value: 'postgresql+asyncpg://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/secure_download?ssl=require' }
        { name: 'DATABASE_URL_SYNC', value: 'postgresql://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/secure_download?sslmode=require' }
        { name: 'STORAGE_BACKEND', value: 'azure_blob' }
        { name: 'ENCRYPTION_KEY', value: encryptionKey }
        { name: 'AZURE_STORAGE_CONNECTION_STRING', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net' }
        { name: 'AZURE_STORAGE_CONTAINER_NAME', value: 'secure-downloads' }
        { name: 'AZURE_TENANT_ID', value: azureTenantId }
        { name: 'AZURE_CLIENT_ID', value: azureClientId }
        { name: 'AZURE_CLIENT_SECRET', value: azureClientSecret }
        { name: 'GRAPH_SENDER_EMAIL', value: graphSenderEmail }
        { name: 'PORTAL_DOMAIN', value: portalDomain }
        { name: 'PROCESSING_MAILBOX', value: processingMailbox }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
      ]
    }
  }
}

// --- Outputs ---
output appServiceUrl string = 'https://${appService.properties.defaultHostName}'
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output postgresHost string = postgresServer.properties.fullyQualifiedDomainName
output storageAccountName string = storageAccount.name
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
