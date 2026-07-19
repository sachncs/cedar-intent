#!/usr/bin/env bash
# End-to-end Todo workflow driven through the cedar-intent CLI.
#
# Usage: bash run.sh

set -euo pipefail

SCOPE_GENERATE=(
    --principal is_type
    --principal-type User
    --action named
    --action-name createTask
    --resource is_type
    --resource-type Task
    --offline
)

SCOPE_APPLY_OWNER=(
    --principal is_type
    --principal-type User
    --action named
    --action-name completeTask
    --resource is_type
    --resource-type Task
)

cedar-intent --workspace . requirement add tasks/requirements/TSK-001.md --domain tasks
cedar-intent --workspace . requirement add tasks/requirements/TSK-002.md --domain tasks

cedar-intent --workspace . policy generate TSK-001 \
    --domain tasks "${SCOPE_GENERATE[@]}"

cedar-intent --workspace . policy apply TSK-001 \
    --domain tasks "${SCOPE_GENERATE[@]}" \
    --no-scenarios

cedar-intent --workspace . policy generate TSK-002 \
    --domain tasks "${SCOPE_APPLY_OWNER[@]}"

cedar-intent --workspace . policy apply TSK-002 \
    --domain tasks "${SCOPE_APPLY_OWNER[@]}" \
    --no-scenarios

cedar-intent --workspace . --json check
cedar-intent --workspace . --json verify --domain tasks
cedar-intent --workspace . deploy bundle --domain tasks --output ./dist/tasks

echo "Workspace ready. Bundle written to dist/tasks."
