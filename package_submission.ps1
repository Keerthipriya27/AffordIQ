$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$archive = Join-Path $root "code.zip"
$include = @(
  "code",
  "evaluation",
  "src",
  "index.html",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "vite.config.ts",
  "README.md",
  "output.csv",
  "validation_statistics.json",
  "dashboard_data.json"
)

if (Test-Path $archive) { Remove-Item $archive -Force }
$paths = $include | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path $_ }
Compress-Archive -Path $paths -DestinationPath $archive -CompressionLevel Optimal
Write-Output "Created $archive"
