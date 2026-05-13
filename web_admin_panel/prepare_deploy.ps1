$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$deploy = Join-Path $root "deploy_ready"
$allowedDirs = @("app", "lib", "public")
$allowedFiles = @(
  "package.json",
  "package-lock.json",
  "next.config.mjs",
  "tsconfig.json",
  "next-env.d.ts",
  "netlify.toml",
  "README.md",
  ".env.example"
)

if (Test-Path -LiteralPath $deploy) {
  $resolved = (Resolve-Path -LiteralPath $deploy).Path
  if (-not $resolved.StartsWith($root)) {
    throw "Unexpected deploy path: $resolved"
  }
  Remove-Item -LiteralPath $resolved -Recurse -Force
}

New-Item -ItemType Directory -Path $deploy | Out-Null

foreach ($dir in $allowedDirs) {
  Copy-Item -LiteralPath (Join-Path $root $dir) -Destination (Join-Path $deploy $dir) -Recurse -Force
}

foreach ($file in $allowedFiles) {
  Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $deploy $file) -Force
}

$forbidden = @(".env", ".env.local", "node_modules", ".next", ".netlify", "out", "dist")
foreach ($item in $forbidden) {
  $matches = Get-ChildItem -LiteralPath $deploy -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $item }
  if ($matches) {
    throw "Forbidden item copied into deploy_ready: $item"
  }
}

Write-Host "deploy_ready hazir: $deploy"
