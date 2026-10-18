#!/bin/bash
# push.sh — stage, commit and push.  Usage: ./push.sh [message]
set -e
cd "$(dirname "$0")"

msg="${*:-Update}"

git add -A

if git diff --cached --quiet; then
  echo "Nothing to commit."
else
  git --no-pager diff --cached --stat
  git commit -m "$msg"
fi

git push || git push -u origin "$(git branch --show-current)"
