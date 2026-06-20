#!/usr/bin/env bash
# Deploy the VERDICT dashboard to GitHub Pages (gh-pages branch).
#
# The live demo is a static export of web/static/ — no Flask backend. app.js
# detects a static host and serves the committed web/static/verdict.json
# snapshot, so the page is fully reproducible with no key and no network.
#
# Mapping (verified): app.js, styles.css, verdict.json are copied verbatim;
# index.html has its two "/static/" asset paths rewritten to relative so the
# project subpath (kesanabalasainadh.github.io/bitbucket/) resolves; .nojekyll
# disables Jekyll so files publish as-is.
#
# Usage: from the repo root, `bash web/deploy_pages.sh`
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SRC="$ROOT/web/static"
BUILD="$(mktemp -d)"
WORKTREE="$(mktemp -d)"
BRANCH="gh-pages"
trap 'rm -rf "$BUILD" "$WORKTREE"; git -C "$ROOT" worktree prune 2>/dev/null || true' EXIT

echo "==> Building static export from $SRC"
cp "$SRC/app.js" "$SRC/styles.css" "$SRC/verdict.json" "$BUILD/"
# Rewrite the two absolute /static/ asset paths to relative for the Pages subpath.
sed 's#/static/##g' "$SRC/index.html" > "$BUILD/index.html"
touch "$BUILD/.nojekyll"

echo "==> Refreshing $BRANCH worktree"
git -C "$ROOT" fetch -q origin "$BRANCH" || true
if git -C "$ROOT" show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
  git -C "$ROOT" worktree add -q --force -B "$BRANCH" "$WORKTREE" "origin/$BRANCH"
else
  git -C "$ROOT" worktree add -q --force --orphan "$WORKTREE" 2>/dev/null \
    || git -C "$ROOT" worktree add -q --force -B "$BRANCH" "$WORKTREE"
fi

echo "==> Syncing files"
# The export is an exact, known file set — copy those, drop nothing stale.
for f in index.html app.js styles.css verdict.json .nojekyll; do
  rm -f "$WORKTREE/$f"
  cp "$BUILD/$f" "$WORKTREE/$f"
done

git -C "$WORKTREE" add -A
if git -C "$WORKTREE" diff --cached --quiet; then
  echo "==> No changes to deploy."
else
  git -C "$WORKTREE" commit -q -m "deploy: VERDICT demo dashboard (static, GitHub Pages)"
  git -C "$WORKTREE" push -q origin "HEAD:$BRANCH"
  echo "==> Pushed to origin/$BRANCH"
fi

echo "==> Live: https://kesanabalasainadh.github.io/bitbucket/"
