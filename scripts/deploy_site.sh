#!/usr/bin/env bash
# Deploy the findings webapp to GitHub Pages on the gh-pages branch.
#
# Workflow:
#   .venv/bin/python scripts/build_site.py    # build into web/
#   bash scripts/deploy_site.sh               # push web/ to gh-pages
#
# First run: bootstraps an orphan gh-pages branch on origin automatically.
# Subsequent runs: incremental commit on top.
#
# After the first deploy, set the Pages source to branch=gh-pages, folder=/
# in GitHub repo settings. The page lives at:
#   https://skspade.github.io/gui-agent-frontier/

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO_ROOT"

# Refuse to run if web/index.html doesn't exist — build forgotten.
if [ ! -f web/index.html ]; then
  echo "error: web/index.html missing. Run scripts/build_site.py first." >&2
  exit 1
fi

ORIGIN_URL=$(git config --get remote.origin.url)

# Bootstrap gh-pages on origin if it doesn't exist.
if ! git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  echo "→ gh-pages not found on origin; bootstrapping ..."
  BOOT=$(mktemp -d -t gh-pages-boot-XXXXXX)
  git -C "$BOOT" init -q -b gh-pages
  git -C "$BOOT" remote add origin "$ORIGIN_URL"
  : > "$BOOT/.nojekyll"
  git -C "$BOOT" add .nojekyll
  git -C "$BOOT" -c user.email=deploy@local -c user.name=deploy \
    commit -q -m "deploy: bootstrap gh-pages"
  git -C "$BOOT" push -q origin gh-pages
  rm -rf "$BOOT"
fi

# Sync web/ into a temporary worktree on gh-pages, commit, push.
WORKTREE=$(mktemp -d -t gh-pages-XXXXXX)
trap 'git worktree remove --force "$WORKTREE" 2>/dev/null || true' EXIT

git fetch -q origin gh-pages
git worktree add -q "$WORKTREE" gh-pages

# Replace contents (preserving .git and .nojekyll).
find "$WORKTREE" -mindepth 1 -maxdepth 1 \
  ! -name .git ! -name .nojekyll -exec rm -rf {} +

cp web/index.html web/app.js web/styles.css "$WORKTREE/"
[ -d web/screenshots ] && cp -r web/screenshots "$WORKTREE/"
[ -f "$WORKTREE/.nojekyll" ] || : > "$WORKTREE/.nojekyll"

cd "$WORKTREE"
git add -A
if git diff --cached --quiet; then
  echo "→ No changes; nothing to deploy."
  exit 0
fi

SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
git commit -q -m "deploy: $SHA"
git push -q origin gh-pages

echo "→ Deployed gh-pages from $SHA"
echo "→ Page: https://skspade.github.io/gui-agent-frontier/"
