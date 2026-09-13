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
  "log.txt",
  "output.csv",
  "validation_statistics.json",
  "dashboard_data.json"
)

if (Test-Path $archive) { Remove-Item $archive -Force }
$staging = Join-Path $env:TEMP ("affordiq-submission-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging -Force | Out-Null
try {
  foreach ($entry in $include) {
    $source = Join-Path $root $entry
    if (-not (Test-Path $source)) { continue }
    if ((Get-Item $source).PSIsContainer) {
      $files = Get-ChildItem $source -File -Recurse | Where-Object {
        $_.FullName -notmatch "\\(__pycache__|node_modules|dist|\.cache|logs)\\" -and
        $_.Extension -notin @(".pyc", ".pyo")
      }
      foreach ($file in $files) {
        $relative = $file.FullName.Substring($root.Length).TrimStart("\")
        $destination = Join-Path $staging $relative
        $destinationDir = Split-Path $destination -Parent
        New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
        Copy-Item $file.FullName $destination -Force
      }
    } else {
      $destination = Join-Path $staging $entry
      $destinationDir = Split-Path $destination -Parent
      if ($destinationDir) { New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null }
      Copy-Item $source $destination -Force
    }
  }
  Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $archive -CompressionLevel Optimal
} finally {
  if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
}
Write-Output "Created $archive"
