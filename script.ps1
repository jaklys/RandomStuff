# =============================================================================
# test_chuck_release.ps1
#
# Direct test of chuck agent POST /release endpoint (bypassing GitLab pipeline).
#   Phase 1: connectivity check via /version (no auth)
#   Phase 2: BAM token acquisition (same as pipeline's win-chuck-release-template)
#   Phase 3: POST /release with real payload
#
# Run from a Windows workstation that is domain-joined (Kerberos SSO needed
# for BAM token). The .config file referenced in $configFile must already exist
# on the NAS — it is created by Watchtower super_recipe_v2.
# =============================================================================

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ---- Target chuck agent --------------------------------------------------
$chuckHost    = "gbrdsm020005206.intranet.barcapint.com"
$chuckPort    = 6302
$chuckScheme  = "https"

# ---- Release parameters (must match what Watchtower saved to NAS) --------
$crNumber     = "CR1111111111"
$releaseDate  = "20260415"
$envKey       = "EMEA-UAT2-A"   # MUST match .config 'env' field + filename suffix
$configFile   = "Recipes\$releaseDate\FIAT~$envKey#$crNumber.config"
$artRoot      = "\\intranet.barcapint.com\dfs-emea\GROUP\Ldn\EDT\FIAT\Artifacts"
$chuckWorkDir = "C:\Program Files\Barclays Capital\EDT\FIAT\Chuck\GL.2024.03.5"
$deployId     = "local-test-$(Get-Date -UFormat %s)"

# ---- BAM (must match chuck agent's JWT_AUDIENCE — FIAT_UAT for UAT agents)
$bamAppName     = "FIAT_UAT"
$bamAuthHost    = "bamuat-auth.client.barclayscorp.com"
$bamRedirectUrl = "http://anyHost"


# =============================================================================
# Phase 1: connectivity check — /version endpoint (no auth)
# =============================================================================
Write-Host "`n=== Phase 1: /version (no auth) ===" -ForegroundColor Cyan
$versionUrl = "$($chuckScheme)://$($chuckHost):$($chuckPort)/version"
Write-Host "GET $versionUrl"
try {
    $v = Invoke-WebRequest -Uri $versionUrl -Method GET -UseBasicParsing
    Write-Host "Status: $($v.StatusCode) — $($v.Content)" -ForegroundColor Green
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Check: is chuck agent running? firewall? TLS cert?"
    exit 1
}


# =============================================================================
# Phase 2: BAM token acquisition
# =============================================================================
Write-Host "`n=== Phase 2: Acquire BAM token ===" -ForegroundColor Cyan
$appEsc   = [uri]::EscapeDataString($bamAppName)
$redirEsc = [uri]::EscapeDataString($bamRedirectUrl)
$bamUrl   = "https://$bamAuthHost/authn/authenticate/sso?appName=$appEsc&redirectURL=$redirEsc"
Write-Host "BAM URL: $bamUrl"

$bamResp = Invoke-WebRequest -Uri $bamUrl -Method GET -UseDefaultCredentials -UseBasicParsing
if ($bamResp.Content -match 'name="bamToken"\s+value="([^"]+)"') {
    $bamToken = $matches[1]
    Write-Host "BAM token acquired (length: $($bamToken.Length))" -ForegroundColor Green
} else {
    Write-Host "bamToken not found in BAM response" -ForegroundColor Red
    exit 1
}


# =============================================================================
# Phase 3: POST /release
# =============================================================================
Write-Host "`n=== Phase 3: POST /release ===" -ForegroundColor Cyan
$releaseUrl = "$($chuckScheme)://$($chuckHost):$($chuckPort)/release"

$payload = @{
    config_file       = $configFile
    art_root          = $artRoot
    chuck_working_dir = $chuckWorkDir
    deploy_id         = $deployId
} | ConvertTo-Json

Write-Host "POST $releaseUrl"
Write-Host "Payload:"
Write-Host $payload

$headers = @{
    "Authorization" = "Bearer $bamToken"
    "Content-Type"  = "application/json"
}

try {
    $releaseResp = Invoke-WebRequest -Uri $releaseUrl `
        -Method POST `
        -Headers $headers `
        -Body $payload `
        -UseBasicParsing `
        -TimeoutSec 900
    Write-Host "`nStatus: $($releaseResp.StatusCode)" -ForegroundColor Green
    Write-Host "Response body:"
    Write-Host $releaseResp.Content
} catch {
    Write-Host "`nFAILED: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $errStream = $_.Exception.Response.GetResponseStream()
        $reader    = New-Object System.IO.StreamReader($errStream)
        $errBody   = $reader.ReadToEnd()
        Write-Host "HTTP Status: $($_.Exception.Response.StatusCode.value__)"
        Write-Host "Error body: $errBody"
    }
    exit 1
}
