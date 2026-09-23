# Publishing

## This repository is PUBLIC

Created at `walkthenose75/copilot-studio-eval-framework` via `INIT-REPO.ps1`
(or `INIT-REPO.sh`). The whole repo — the code and the briefing — is public, and
the briefing is served live by GitHub Pages.

```powershell
.\INIT-REPO.ps1
```

The script refuses to run if a `.env` file is present, fails fast if the GitHub
CLI is missing or unauthenticated, creates the repo as **public**, pushes, and
enables GitHub Pages (`main` → `/docs`).

## Live briefing

Once the script finishes and Pages has built (a minute or two on first publish):

```
https://walkthenose75.github.io/copilot-studio-eval-framework/
```

`docs/.nojekyll` tells Pages to serve the files as-is, and `docs/index.html` is
fully self-contained (no build step, no external dependencies), so it renders
identically whether opened locally, sent as a file, or served from Pages.

## Enabling Pages by hand (if you didn't use the script)

```powershell
gh api -X POST repos/walkthenose75/copilot-studio-eval-framework/pages `
  -f 'source[branch]=main' -f 'source[path]=/docs'
```

Or in the GitHub UI: **Settings → Pages → Build and deployment → Source: Deploy
from a branch → Branch: `main` / folder: `/docs` → Save.**

**Before making anything public:** the briefing contains no customer name and no
internal Microsoft content by design — every claim cites public Microsoft
documentation. Confirm that still holds after any edit you make.

## A note on the starter-pack workflows

`starter-pack/workflows/*.yml` are **templates**, deliberately not in
`.github/workflows/`. If they were, GitHub would try to run them on every push
and fail on missing secrets. Copy them into `.github/workflows/` in the
repository where your agent solution lives.

## Verify after pushing

- `git log --oneline` shows your commit
- The repo is marked **Public** on GitHub
- **Settings → Pages** shows the site building/published at the URL above
- No `.env` in the file list; `.env.template` is present
- `starter-pack/samples/` contains only `README.md` — captured API responses
  must be scrubbed before they are ever committed
