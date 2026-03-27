param location string = resourceGroup().location
param tags object = {}
param applicationInsightsName string
param storageAccountName string
param storageResourceGroupName string
param searchServiceResourceGroupName string
param openAiResourceGroupName string
param documentIntelligenceResourceGroupName string
param appEnvVariables object
param functionName string

var abbrs = loadJsonContent('../abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, location, functionName))

var runtimeStorageName = '${abbrs.storageStorageAccounts}mdl${take(resourceToken, 18)}'
var hostId = 'mdl-auto-${take(resourceToken, 12)}'

var runtimeStorageRoles = [
  {
    suffix: 'blob'
    roleDefinitionId: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  }
  {
    suffix: 'queue'
    roleDefinitionId: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  }
  {
    suffix: 'table'
    roleDefinitionId: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  }
]

var deploymentContainerName = 'app-package-deployment'
var appInsightsIdentity = 'ClientId=${autoIndexerIdentity.outputs.clientId};Authorization=AAD'

module runtimeStorageAccount '../core/storage/storage-account.bicep' = {
  name: 'moodle-auto-indexer-runtime-storage'
  params: {
    name: runtimeStorageName
    location: location
    tags: tags
    allowBlobPublicAccess: false
    containers: [
      {
        name: deploymentContainerName
      }
    ]
  }
}

resource runtimeStorage 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: runtimeStorageName
}

resource contentStorage 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  scope: resourceGroup(storageResourceGroupName)
  name: storageAccountName
}

module autoIndexerIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.1' = {
  name: 'moodle-auto-indexer-identity'
  params: {
    location: location
    tags: tags
    name: 'moodle-auto-indexer-identity-${resourceToken}'
  }
}

resource runtimeStorageRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in runtimeStorageRoles: {
  name: guid(runtimeStorage.id, role.roleDefinitionId, 'moodle-auto-indexer-runtime')
  scope: runtimeStorage
  properties: {
    principalId: autoIndexerIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', role.roleDefinitionId)
  }
  dependsOn: [
    runtimeStorageAccount
  ]
}]

module autoIndexerPlan 'br/public:avm/res/web/serverfarm:0.1.1' = {
  name: 'moodle-auto-indexer-plan'
  params: {
    name: '${abbrs.webServerFarms}moodle-auto-indexer-${resourceToken}'
    sku: {
      name: 'FC1'
      tier: 'FlexConsumption'
    }
    reserved: true
    location: location
    tags: tags
  }
}

var baseAppSettings = {
  AzureWebJobsStorage__credential: 'managedidentity'
  AzureWebJobsStorage__clientId: autoIndexerIdentity.outputs.clientId
  AzureWebJobsStorage__blobServiceUri: runtimeStorage.properties.primaryEndpoints.blob
  AzureWebJobsStorage__queueServiceUri: runtimeStorage.properties.primaryEndpoints.queue
  AzureWebJobsStorage__tableServiceUri: runtimeStorage.properties.primaryEndpoints.table
  FUNCTIONS_EXTENSION_VERSION: '~4'
  AZURE_CLIENT_ID: autoIndexerIdentity.outputs.clientId
}

var appInsightsSettings = !empty(applicationInsightsName) ? {
  APPLICATIONINSIGHTS_AUTHENTICATION_STRING: appInsightsIdentity
  APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.?properties.ConnectionString ?? ''
} : {}

var autoIndexerSettings = {
  AzureFunctionsWebHost__hostid: hostId
  MOODLE_AUTO_INDEX_TRIGGER_CONTAINER: appEnvVariables.AZURE_STORAGE_CONTAINER
  MOODLE_AUTO_INDEX_SOURCE_PREFIX: 'nerilio/Nerilio-Moodle'
  MOODLE_AUTO_INDEX_TARGET_PREFIX: 'moodle'
  MOODLE_AUTO_INDEX_CATEGORY: 'moodle'
  MOODLE_AUTO_INDEX_ALLOWED_EXTENSIONS: '.xml'
  MOODLE_AUTO_INDEX_STORAGE__credential: 'managedidentity'
  MOODLE_AUTO_INDEX_STORAGE__clientId: autoIndexerIdentity.outputs.clientId
  MOODLE_AUTO_INDEX_STORAGE__blobServiceUri: contentStorage.properties.primaryEndpoints.blob
  MOODLE_AUTO_INDEX_STORAGE__queueServiceUri: contentStorage.properties.primaryEndpoints.queue
}

var allAppSettings = union(appEnvVariables, baseAppSettings, appInsightsSettings, autoIndexerSettings)

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(applicationInsightsName)) {
  name: applicationInsightsName
}

module autoIndexerFunctionApp 'br/public:avm/res/web/site:0.15.1' = {
  name: 'moodle-auto-indexer-app'
  params: {
    kind: 'functionapp,linux'
    name: functionName
    location: location
    tags: union(tags, { 'azd-service-name': 'moodle-auto-indexer' })
    serverFarmResourceId: autoIndexerPlan.outputs.resourceId
    managedIdentities: {
      userAssignedResourceIds: [
        '${autoIndexerIdentity.outputs.resourceId}'
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${runtimeStorage.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: autoIndexerIdentity.outputs.resourceId
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: 2048
        maximumInstanceCount: 50
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
    }
    siteConfig: {
      alwaysOn: false
      httpsOnly: true
      ftpsState: 'Disabled'
      cors: {
        allowedOrigins: ['https://portal.azure.com']
      }
    }
    appSettingsKeyValuePairs: allAppSettings
  }
  dependsOn: [
    runtimeStorageAccount
  ]
}

module autoIndexerRbac 'functions-rbac.bicep' = {
  name: 'moodle-auto-indexer-rbac'
  params: {
    principalId: autoIndexerIdentity.outputs.principalId
    storageResourceGroupName: storageResourceGroupName
    searchServiceResourceGroupName: searchServiceResourceGroupName
    openAiResourceGroupName: openAiResourceGroupName
    documentIntelligenceResourceGroupName: documentIntelligenceResourceGroupName
    visionServiceName: ''
    visionResourceGroupName: ''
    contentUnderstandingServiceName: ''
    contentUnderstandingResourceGroupName: ''
    useMultimodal: false
  }
}

output name string = autoIndexerFunctionApp.outputs.name
output defaultHostname string = autoIndexerFunctionApp.outputs.defaultHostname
output principalId string = autoIndexerIdentity.outputs.principalId
