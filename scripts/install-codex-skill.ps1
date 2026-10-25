<#
.SYNOPSIS
Install the wireless investigation skill as a live directory junction for Codex.
.DESCRIPTION
Default destination: the current user's .agents\skills directory.
The junction points at this checkout, so local edits and Git updates are visible
without recopying the skill. Keep the source checkout at its installed location.
Codex detects skill changes; restart Codex if a running session retains old metadata.
This does not fetch changes made only on GitHub. Sync those into the checkout first.
No existing directory is replaced and no Codex configuration is changed.
.PARAMETER SourcePath
The skill directory. Defaults to skills\analyze-wireless-causality in this checkout.
.PARAMETER SkillRoot
The directory in which Codex discovers skills. Defaults to ~/.agents/skills.
.PARAMETER VerifyOnly
Check an existing junction and file hashes without creating anything.
.EXAMPLE
.\scripts\install-codex-skill.ps1
.EXAMPLE
.\scripts\install-codex-skill.ps1 -VerifyOnly
#>
[CmdletBinding()]
param(
    [string]$SourcePath = (Join-Path $PSScriptRoot '..\skills\analyze-wireless-causality'),
    [string]$SkillRoot = (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.agents\skills'),
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This installer uses Windows directory junctions. On other systems use a directory symlink.'
}

function Normalize-Path([string]$Value) {
    return ($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Value)).TrimEnd([char[]]'\/')
}

$skillName = 'analyze-wireless-causality'
$source = Normalize-Path ((Resolve-Path -LiteralPath $SourcePath).ProviderPath)
$root = Normalize-Path $SkillRoot
$linkPath = Join-Path $root $skillName
if ($source -eq $linkPath -or $source.StartsWith($linkPath + '\', [StringComparison]::OrdinalIgnoreCase) -or $linkPath.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The source and destination must be separate directories, without nesting.'
}

$manifestPath = Join-Path $source 'SKILL.md'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Missing source SKILL.md: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
if ($manifest -notmatch '(?m)^name:\s*analyze-wireless-causality\s*$') {
    throw 'The source does not declare the expected skill name.'
}
foreach ($required in @('agents\openai.yaml', 'tools\check_environment.py', 'references\tool-contracts.md')) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $required) -PathType Leaf)) {
        throw "Incomplete source skill: $required is missing."
    }
}

$existing = Get-Item -LiteralPath $linkPath -Force -ErrorAction SilentlyContinue
$created = $false
if ($null -eq $existing) {
    if ($VerifyOnly) { throw "The skill is not installed at $linkPath" }
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    New-Item -ItemType Junction -Path $linkPath -Target $source | Out-Null
    $created = $true
} elseif ($existing.LinkType -ne 'Junction') {
    throw "Destination already exists and is not a junction; nothing was replaced: $linkPath"
}

$installed = Get-Item -LiteralPath $linkPath -Force
$targets = @($installed.Target)
if ($installed.LinkType -ne 'Junction' -or $targets.Count -ne 1 -or (Normalize-Path $targets[0]) -ne $source) {
    throw "The existing junction points elsewhere; nothing was replaced: $linkPath"
}

# Verify reusable files; private investigations stay in the source checkout.
# Get-ChildItem does not follow nested junctions/symlinks during recursion.
$files = @(Get-ChildItem -LiteralPath $source -Recurse -File -Force | Where-Object {
    $relative = $_.FullName.Substring($source.Length + 1)
    $relative -notmatch '^(logs|results)\\' -and
    $relative -notmatch '^tools\\runs\\' -and
    $relative -notmatch '(^|\\)__pycache__\\' -and
    $relative -notmatch '\.py[co]$'
})
if ($files.Count -lt 1) { throw 'No reusable source files found.' }
foreach ($file in $files) {
    $relative = $file.FullName.Substring($source.Length + 1)
    $linkedFile = Join-Path $linkPath $relative
    $sourceHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    $linkedHash = (Get-FileHash -LiteralPath $linkedFile -Algorithm SHA256).Hash
    if ($sourceHash -ne $linkedHash) { throw "File mismatch or concurrent edit: $relative" }
}

[pscustomobject]@{
    Status = $(if ($created) { 'installed' } else { 'verified' })
    Skill = $skillName
    GlobalEntry = $linkPath
    Source = $source
    LinkType = $installed.LinkType
    FilesVerified = $files.Count
    UpdateMode = 'live-local-checkout'
    NextStep = 'Invoke $analyze-wireless-causality in Codex; restart if it has not refreshed.'
}
