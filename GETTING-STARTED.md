# Getting started

You just opened this in VS Code. Here is the 60-second orientation.

## What this repository is

Two deliverables for the Copilot Studio enterprise evaluation engagement:

| Folder | What it is | Status |
|---|---|---|
| `docs/` | The customer briefing — an interactive page, published via GitHub Pages | **Ready to share.** Every claim cited to Microsoft docs |
| `starter-pack/` | A working implementation: runner, Dataverse repo, CI/CD gate, Power BI | **Reference implementation — pending shakeout** |

Those two are at different maturity levels. Do not describe the starter pack as
"proven" until `starter-pack/SHAKEDOWN.md` is complete.

## First three commands

```powershell
cd starter-pack
python -m pip install -r requirements.txt
python verify_package.py          # 28 offline checks, no auth needed
```

If that comes back clean, the package is structurally sound. It proves nothing
about live API behaviour — that is what the shakeout is for.

## Then what

1. **`starter-pack/.github/PROVENANCE.md`** — read this before telling anyone
   the status. It splits verified / tested-against-mock / unverified.
2. **`starter-pack/SHAKEDOWN.md`** — the 7-step runbook that makes it proven.
   About 3 hours against a sandbox environment.
3. **`starter-pack/SETUP.md`** — full configuration walkthrough.
4. **`PUBLISH.md`** — publishing `docs/` to GitHub Pages.

## Working with GitHub Copilot in this repo

`starter-pack/.github/copilot-instructions.md` is picked up automatically by
GitHub Copilot in VS Code. It carries the repo rules — most importantly:

- Never invent API behaviour; capture a real response and code to it
- Never widen a quality gate to make it pass
- Never let `runOnPublishedBot` inherit a default

A good opening prompt once you are authenticated:

> Read `.github/PROVENANCE.md` and `SHAKEDOWN.md`. Then walk me through
> step 1, and stop after each step so I can confirm before you continue.

VS Code tasks for each shakeout step are in `.vscode/tasks.json` —
**Terminal → Run Task**.

## Before you publish anything publicly

This repository is intended to become a **public** GitHub Pages site. Before
pushing:

- No customer name in the repo name, commit messages, or page content
- `starter-pack/samples/*.json` are real API responses and may contain data
  drawn from knowledge sources — scrub or leave them untracked
- `.env` is git-ignored; confirm no connection IDs or secrets are staged
