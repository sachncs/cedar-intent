#!/usr/bin/env bash
# End-to-end PhotoFlash workflow driven through the cedar-intent CLI.
#
# Usage: bash scripts/run.sh
#
# All commands run offline (no LLM calls) so this script is safe to
# execute in CI.

set -euo pipefail

SCOPE_GENERATE=(
    --principal specific
    --principal-type User
    --entity-id alice
    --action named
    --action-name viewPhoto
    --resource is_type
    --resource-type Photo
    --offline
)

SCOPE_APPLY=(
    --principal specific
    --principal-type User
    --entity-id alice
    --action named
    --action-name viewPhoto
    --resource is_type
    --resource-type Photo
)

cedar-intent --workspace . requirement add hr/requirements/HR-001.md --domain hr
cedar-intent --workspace . requirement add hr/requirements/HR-042.md --domain hr

cedar-intent --workspace . policy generate HR-042 \
    --domain hr "${SCOPE_GENERATE[@]}"

cedar-intent --workspace . policy apply HR-042 \
    --domain hr "${SCOPE_APPLY[@]}" \
    --no-scenarios

cedar-intent --workspace . policy generate HR-001 \
    --domain hr "${SCOPE_GENERATE[@]}"

cedar-intent --workspace . policy apply HR-001 \
    --domain hr "${SCOPE_APPLY[@]}" \
    --no-scenarios

cedar-intent --workspace . --json check
cedar-intent --workspace . --json verify --domain hr
cedar-intent --workspace . deploy bundle --domain hr --output ./dist/hr

echo "Workspace ready. Bundle written to dist/hr."
