#!/usr/bin/env bash
# Move autosar-agent-skills from the personal account into an organisation, so
# every public URL becomes github.com/<org>/... instead of github.com/<login>/...
#
# Run this only after the organisation exists on BOTH hosts. GitHub has no API
# to create an org (web UI only, and it blocks non-browser clients), so that
# part is manual:
#
#   GitHub  https://github.com/account/organizations/new
#   Gitea   already done — the org is autosar-skills on 123.207.197.200:56789
#
# Usage:
#   bash scripts/migrate-to-org.sh --check          # report, change nothing
#   bash scripts/migrate-to-org.sh autosar-skills   # do the migration
#
# Exit codes: 0 ok, 1 precondition failed, 2 bad usage.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REPO="autosar-agent-skills"
GH_LOGIN="ZhaoBoxiong"
GITEA_HOST="123.207.197.200:56789"
SITE="$HOME/.openclaw/workspace/projects/personal-site"
BLOG="$SITE/site/blog/dbc-matrix-audit-skill.html"

ORG="${1:-}"
CHECK=0
case "$ORG" in
  --check) CHECK=1; ORG="autosar-skills" ;;
  ""|-h|--help)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
esac

say() { printf '%-6s %s\n' "$1" "$2"; }
die() { say FAIL "$1"; exit 1; }

# ---------------------------------------------------------------- preconditions
say 1/6 "preconditions"

if [[ "$CHECK" == 1 ]]; then
  gh api "orgs/$ORG" --silent >/dev/null 2>&1 \
    && say ok "GitHub org $ORG exists" \
    || say -- "GitHub org $ORG missing (create it in the web UI first)"

  gh api "repos/$GH_LOGIN/$REPO" --jq '"still owned by '"$GH_LOGIN"': \(.full_name)"' 2>/dev/null \
    || say -- "repo already moved off $GH_LOGIN"

  tea repos list --owner "$ORG" 2>/dev/null | grep -q "$REPO" \
    && say ok "Gitea org $ORG already has $REPO" \
    || say -- "Gitea side not migrated"

  say done "no changes made"
  exit 0
fi

gh api "orgs/$ORG" --silent >/dev/null 2>&1 \
  || die "GitHub org '$ORG' does not exist. Create it at https://github.com/account/organizations/new"

# gh needs the admin:org scope-adjacent repo scope to accept the transfer; the
# API returns 202 with a transfer object, and the repo path changes only after
# GitHub processes it, so poll rather than assume.
say 2/6 "transfer on GitHub"
if gh api "repos/$ORG/$REPO" --silent >/dev/null 2>&1; then
  say skip "already at $ORG/$REPO"
else
  gh api -X POST "repos/$GH_LOGIN/$REPO/transfer" -f new_owner="$ORG" >/dev/null \
    || die "transfer request rejected"
  for i in $(seq 1 30); do
    gh api "repos/$ORG/$REPO" --silent >/dev/null 2>&1 && break
    sleep 2
  done
  gh api "repos/$ORG/$REPO" --silent >/dev/null 2>&1 || die "transfer did not land within 60s"
  say ok "now $ORG/$REPO"
fi

# ------------------------------------------------------------------- remotes
say 3/6 "remotes"
git remote set-url github "https://github.com/$ORG/$REPO.git"
git remote set-url gitea  "http://$GITEA_HOST/$ORG/$REPO.git"
git remote -v | sed 's/^/       /'

# ---------------------------------------------------------------------- links
say 4/6 "public links"
# Old owner -> org, in the places a reader can actually click.
OLD="github.com/$GH_LOGIN/$REPO"
NEW="github.com/$ORG/$REPO"
changed=0
for f in README.md; do
  if grep -q "$OLD" "$f"; then
    sed -i "s|$OLD|$NEW|g" "$f"
    say ok "$f"
    changed=1
  fi
done
if [[ -f "$BLOG" ]] && grep -q "$OLD" "$BLOG"; then
  sed -i "s|$OLD|$NEW|g" "$BLOG"
  say ok "blog post (visible text and href)"
  changed=1
fi
[[ "$changed" == 1 ]] || say skip "no references found"

say 5/6 "release notes"
# Release assets and the release page itself live under the repo, and GitHub
# 301s old paths, but the notes contain absolute links that would stay wrong.
mapfile -t TAGS < <(gh release list --repo "$ORG/$REPO" --limit 20 --json tagName --jq '.[].tagName' 2>/dev/null || true)
if ((${#TAGS[@]})); then
  for t in "${TAGS[@]}"; do
    body="$(gh release view "$t" --repo "$ORG/$REPO" --json body --jq .body 2>/dev/null || true)"
    if [[ "$body" == *"$OLD"* ]]; then
      printf '%s' "${body//$OLD/$NEW}" | gh release edit "$t" --repo "$ORG/$REPO" --notes-file - >/dev/null
      say ok "release $t"
    fi
  done
else
  say skip "no releases"
fi

# --------------------------------------------------------------------- commit
say 6/6 "commit and push"
git add -A
if git diff --cached --quiet; then
  say skip "nothing to commit"
else
  git commit -q -m "chore: move to the $ORG organisation

Public URLs become github.com/$ORG/$REPO — the path no longer carries a
personal login, so the repository link on the CV and the blog resolves to the
project rather than to an individual account."
  git push -q gitea main && git push -q github main
  say ok "pushed to both remotes"
fi

echo
say done "migration complete"
say live "https://github.com/$ORG/$REPO"
say todo "redeploy the site so the blog picks up the new link:"
echo "       cd $SITE && bash release.sh <version>"
