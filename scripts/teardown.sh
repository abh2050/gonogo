#!/usr/bin/env bash
# Destroy every GoNoGo stack and confirm that nothing billable is left in us-east-2.
# Neptune Serverless bills at minimum capacity while idle, so run this after every AWS session.
set -euo pipefail

PROFILE="awsnew"
REGION="us-east-2"
cd "$(dirname "$0")/../infra"

AWS_PROFILE="$PROFILE" AWS_REGION="$REGION" npx --yes aws-cdk@2 destroy --all --force

clusters=$(aws neptune describe-db-clusters --profile "$PROFILE" --region "$REGION" \
  --query "DBClusters[?starts_with(DBClusterIdentifier, 'gonogo')].DBClusterIdentifier" --output text)
services=$(aws ecs list-clusters --profile "$PROFILE" --region "$REGION" \
  --query "clusterArns[?contains(@, 'gonogo')]" --output text)

if [[ -n "$clusters" || -n "$services" ]]; then
  echo "Teardown incomplete. Remaining Neptune clusters: ${clusters:-none}. ECS clusters: ${services:-none}." >&2
  exit 1
fi
echo "Teardown complete. No GoNoGo Neptune cluster or ECS cluster remains in $REGION."
