#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH=$REPO_ROOT/dist/cross-region-importer.yml
EXPORTER_SSM_PARAMETER_NAME="/cfn-cross-region-exporter/table-arns"
VERSION=$(git describe --always --tags)

if [ ! -f "$IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH" ]; then
  echo "Error: Generated template not found at: $IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH"
  exit 1
fi

values=$(aws ssm get-parameters --names "$EXPORTER_SSM_PARAMETER_NAME" --region us-east-1 | jq -r '.Parameters[].Value')

if [ -z "$values" ]; then
  echo "Error: No table ARNs found in SSM Parameter Store."
  exit 1
fi

IFS=',' read -ra TABLES_ARN <<<"$values"
for i in "${TABLES_ARN[@]}"; do
  IFS='|' read -r SOURCE_REGION TABLE_ARN <<<"$i"
  IMPORTER_STACK_NAME="$SOURCE_REGION-CrossRegionImporter"

  echo "Deploying stack for table ARN: $IMPORTER_STACK_NAME"
  sam deploy --template-file "$IMPORTER_GENERATED_TEMPLATE_ABSOLUTE_PATH" --stack-name "$IMPORTER_STACK_NAME" --capabilities CAPABILITY_IAM --parameter-overrides CrossStackRefTableArn="$TABLE_ARN" Version="$VERSION" --no-fail-on-empty-changeset
done
