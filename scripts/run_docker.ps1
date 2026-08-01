param(
    [string]$ImageName = "cisco-sdwan-mcp",
    [string]$ContainerName = "cisco-sdwan-mcp",
    [int]$HostPort = 8000,
    [string]$EnvFile,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..")

if (-not $EnvFile) {
    $EnvFile = Join-Path $RootDir ".env"
}

if (-not $NoBuild) {
    docker build -t $ImageName $RootDir
}

$ExistingContainer = docker ps -aq --filter "name=^/$ContainerName$"
if ($ExistingContainer) {
    docker rm -f $ContainerName | Out-Null
}

# vManage credentials come from .env so they never land in shell history or
# `docker inspect` output as literal arguments.
$EnvArgs = @()
if (Test-Path $EnvFile) {
    $EnvArgs = @("--env-file", $EnvFile)
} else {
    Write-Warning "$EnvFile not found - the server will start but every tool will report a ConfigurationError until SDWAN_* is set. Run: Copy-Item .env.example .env"
}

docker run --rm -it `
    --name $ContainerName `
    -p "${HostPort}:8000" `
    @EnvArgs `
    -e MCP_TRANSPORT=http `
    -e MCP_HOST=0.0.0.0 `
    -e MCP_PORT=8000 `
    $ImageName
