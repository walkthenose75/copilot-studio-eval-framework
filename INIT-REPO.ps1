<#
    Creates the PUBLIC GitHub repo at walkthenose75, pushes this folder, and
    enables GitHub Pages (main -> /docs) so the briefing is live.

    Run from inside this folder:
        .\INIT-REPO.ps1

    Requires GitHub CLI (winget install GitHub.cli) and `gh auth login` once.
#>

$ErrorActionPreference = 'Stop'
$RepoName = 'copilot-studio-eval-framework'
$Owner    = 'walkthenose75'

Write-Host "Preflight..." -ForegroundColor Cyan
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI not found. Install: winget install GitHub.cli, then: gh auth login"
}
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Not authenticated. Run: gh auth login" }

# Refuse to publish secrets.
if (Test-Path .env) { throw "A .env file is present. Remove it before pushing - it may contain connection IDs or secrets." }
$stray = Get-ChildItem -Recurse -Filter '*.env' -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -ne '.env.template' }
if ($stray) { throw "Environment files found: $($stray.FullName -join ', ')" }

Write-Host "Initialising git..." -ForegroundColor Cyan
if (-not (Test-Path .git)) { git init -b main | Out-Null }
git add -A
git commit -m "Copilot Studio enterprise evaluation framework - briefing site and starter pack" | Out-Null

Write-Host "Creating PUBLIC repo $Owner/$RepoName..." -ForegroundColor Cyan
gh repo create "$Owner/$RepoName" --public --source=. --remote=origin --push

Write-Host "Enabling GitHub Pages (main -> /docs)..." -ForegroundColor Cyan
try {
    gh api -X POST "repos/$Owner/$RepoName/pages" -f "source[branch]=main" -f "source[path]=/docs" | Out-Null
} catch {
    Write-Host "Pages may already be enabled, or will finish provisioning shortly." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Repository:   https://github.com/$Owner/$RepoName" -ForegroundColor Green
Write-Host "Live briefing:      https://$Owner.github.io/$RepoName/" -ForegroundColor Green
Write-Host "(Pages can take a minute or two to build on first publish.)" -ForegroundColor Yellow
