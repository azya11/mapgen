<#
.SYNOPSIS
  Push the mapgen generation worker to a Hugging Face Space (Docker SDK).

.DESCRIPTION
  Clones your (already-created) HF Space repo, copies the worker files into it
  (root Dockerfile, requirements-mapgen.txt, the mapgen/ and worker/ packages,
  and the HF README with config frontmatter), commits and pushes.

.EXAMPLE
  .\scripts\deploy-hf-space.ps1 -HfUser yourname -HfToken hf_xxx
  .\scripts\deploy-hf-space.ps1 -HfUser yourname -HfToken hf_xxx -SpaceName mapgen-worker
#>
param(
  [Parameter(Mandatory = $true)][string]$HfUser,
  [Parameter(Mandatory = $true)][string]$HfToken,
  [string]$SpaceName = "mapgen-worker"
)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$tmp  = Join-Path $env:TEMP "hf-space-$SpaceName"
$url  = "https://${HfUser}:${HfToken}@huggingface.co/spaces/${HfUser}/${SpaceName}"

if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }

Write-Host "Cloning Space https://huggingface.co/spaces/$HfUser/$SpaceName ..."
git clone $url $tmp
if (-not $?) { throw "Clone failed. Create the Space first (Docker SDK) and check your username/token." }

Write-Host "Copying worker files into the Space..."
Copy-Item "$repo\Dockerfile"                 "$tmp\Dockerfile"               -Force
Copy-Item "$repo\requirements-mapgen.txt"    "$tmp\requirements-mapgen.txt"  -Force
Copy-Item "$repo\worker\hf-space-README.md"  "$tmp\README.md"                -Force
foreach ($d in @("mapgen", "worker")) {
  if (Test-Path "$tmp\$d") { Remove-Item -Recurse -Force "$tmp\$d" }
  Copy-Item "$repo\$d" "$tmp\$d" -Recurse -Force
}
# The HF readme lives at the Space root as README.md, not inside worker/.
Remove-Item "$tmp\worker\hf-space-README.md" -Force -ErrorAction SilentlyContinue

Push-Location $tmp
try {
  git add -A
  git -c user.email="$HfUser@users.noreply.huggingface.co" -c user.name="$HfUser" commit -m "Deploy mapgen worker"
  git push
  Write-Host "`nDone. The Space will now build (a few minutes)."
  Write-Host "Health: https://$HfUser-$SpaceName.hf.space/health  ->  {""ok"":true,""configured"":true}"
}
finally {
  Pop-Location
}
