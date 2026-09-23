#!/usr/bin/env bash
# Creates the PUBLIC GitHub repo at walkthenose75, pushes this folder, and
# enables GitHub Pages (main -> /docs) so the briefing is live.
# Requires: gh (GitHub CLI), authenticated via `gh auth login`.
set -euo pipefail
REPO="copilot-studio-eval-framework"
OWNER="walkthenose75"

command -v gh >/dev/null || { echo "GitHub CLI not found. Install it, then: gh auth login"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Not authenticated. Run: gh auth login"; exit 1; }

[ -f .env ] && { echo "ERROR: .env present - remove before pushing."; exit 1; }
found=$(find . -name '*.env' ! -name '.env.template' 2>/dev/null || true)
[ -n "$found" ] && { echo "ERROR: environment files found: $found"; exit 1; }

[ -d .git ] || git init -b main
git add -A
git commit -m "Copilot Studio enterprise evaluation framework - briefing site and starter pack"
gh repo create "$OWNER/$REPO" --public --source=. --remote=origin --push

echo "Enabling GitHub Pages (main -> /docs)..."
gh api -X POST "repos/$OWNER/$REPO/pages" -f 'source[branch]=main' -f 'source[path]=/docs' \
  >/dev/null 2>&1 || echo "Pages may already be enabled, or will finish provisioning shortly."

echo
echo "Done. Repository:  https://github.com/$OWNER/$REPO"
echo "Live briefing:     https://$OWNER.github.io/$REPO/"
echo "(Pages can take a minute or two to build on first publish.)"
