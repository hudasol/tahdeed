#!/usr/bin/env bash
# Push the milestone tags. The build sandbox could not push tags (HTTP 403), so run this once
# from your own machine:  bash scripts/tag-milestones.sh
set -euo pipefail
git fetch origin
for t in $(git tag -l 'v*'); do echo "pushing $t"; done
git push origin --tags
