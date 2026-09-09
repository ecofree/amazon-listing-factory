[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Category,

    [Parameter(Mandatory = $true)]
    [string]$Asin,

    [Parameter(Mandatory = $true)]
    [string]$Brand,

    [Parameter(Mandatory = $true)]
    [string]$SkuPrefix,

    [Parameter(Mandatory = $true)]
    [string]$Manufacturer,

    [Parameter(Mandatory = $true)]
    [string]$Country,

    [Parameter(Mandatory = $true)]
    [string]$Condition,

    [Parameter(Mandatory = $true)]
    [string]$Quantity,

    [Parameter(Mandatory = $true)]
    [string]$Fulfillment,

    [Parameter(Mandatory = $true)]
    [string]$ListPrice,

    [Parameter(Mandatory = $true)]
    [bool]$GtinExempt,

    [string]$Config = "",
    [string]$Template = "",
    [string]$ShippingTemplate = "",
    [string]$ProductIdType = "",
    [string]$ProductId = "",
    [string]$Marketplace = "US",
    [int]$Workers = 0,
    [switch]$Upload,
    [switch]$WriteExcel,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Factory = Join-Path $Root "scripts\factory.py"

if ([string]::IsNullOrWhiteSpace($Config)) {
    $LocalConfig = Join-Path $Root "config.local.env"
    if (Test-Path $LocalConfig) {
        $Config = $LocalConfig
    }
}

$Python = $env:AMAZON_FACTORY_PYTHON
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = "D:\anaconda\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "AMAZON_FACTORY_PYTHON is not set and the project Python was not found: $Python"
}

if ($PlanOnly -or $WhatIfPreference) {
    Write-Host "PRODUCTION_PLAN_ONLY"
    Write-Host "Category: $Category"
    Write-Host "Asin: $Asin"
    Write-Host "Brand: $Brand"
    Write-Host "SkuPrefix: $SkuPrefix"
    Write-Host "Manufacturer: $Manufacturer"
    Write-Host "Country: $Country"
    Write-Host "Condition: $Condition"
    Write-Host "Quantity: $Quantity"
    Write-Host "Fulfillment: $Fulfillment"
    Write-Host "ListPrice: $ListPrice"
    Write-Host "GtinExempt: $GtinExempt"
    Write-Host "Config: $Config"
    Write-Host "Template: $Template"
    Write-Host "Marketplace: $Marketplace"
    Write-Host "Workers: $Workers"
    Write-Host "Python: $Python"
    Write-Host "Upload: $Upload"
    return
}

if (-not $Upload) {
    throw "run_full_job.ps1 production mode requires -Upload so final templates receive usable R2 image URLs."
}

$newArgs = @(
    $Factory,
    "new-job",
    "--category", $Category,
    "--asin", $Asin,
    "--brand", $Brand,
    "--sku-prefix", $SkuPrefix,
    "--marketplace", $Marketplace,
    "--manufacturer", $Manufacturer,
    "--country", $Country,
    "--condition", $Condition,
    "--quantity", $Quantity,
    "--fulfillment", $Fulfillment,
    "--list-price", $ListPrice
)
if ($GtinExempt) {
    $newArgs += "--gtin-exempt"
} else {
    $newArgs += "--not-gtin-exempt"
    $newArgs += @("--product-id-type", $ProductIdType, "--product-id", $ProductId)
}
if (-not [string]::IsNullOrWhiteSpace($ShippingTemplate)) {
    $newArgs += @("--shipping-template", $ShippingTemplate)
}
if (-not [string]::IsNullOrWhiteSpace($Config)) {
    $newArgs += @("--config", $Config)
}
if (-not [string]::IsNullOrWhiteSpace($Template)) {
    $newArgs += @("--template", $Template)
}

Write-Host "Creating job for $Category / $Asin ..."
$newOutput = (& $Python @newArgs 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "new-job failed with exit code $LASTEXITCODE`n$newOutput"
}
$jobInfo = $newOutput | ConvertFrom-Json
$Job = [string]$jobInfo.job
Write-Host "Job: $Job"

$runArgs = @(
    $Factory,
    "run",
    "--job", $Job,
    "--production",
    "--workers", [string]$Workers,
    "--template-mode", "submit_ready"
)
if (-not [string]::IsNullOrWhiteSpace($Config)) {
    $runArgs += @("--config", $Config)
}
if ($Upload) {
    $runArgs += "--upload"
}
if ($WriteExcel) {
    $runArgs += "--write-excel"
}
Write-Host "Running production pipeline"
& $Python @runArgs
$PipelineExitCode = $LASTEXITCODE
if ($PipelineExitCode -eq 3) {
    Write-Host "Automatic QA passed for reviewable candidates. Review them with factory.py review, then resume this job."
}
elseif ($PipelineExitCode -eq 4) {
    Write-Host "Partial production completed. Approved images remain publishable, but no submit-ready family template was produced."
}
elseif ($PipelineExitCode -ne 0) {
    throw "pipeline run failed with exit code $PipelineExitCode"
}

Write-Host "Final status:"
& $Python $Factory "status" "--job" $Job
$StatusExitCode = $LASTEXITCODE
if ($StatusExitCode -ne 0) {
    throw "status command failed with exit code $StatusExitCode"
}
exit $PipelineExitCode
