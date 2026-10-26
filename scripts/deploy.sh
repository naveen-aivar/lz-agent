#!/usr/bin/env bash
# Deploys the PLATFORM into the account/region of your current AWS credentials. Creates real resources: review first.
# Usage: scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id> [image-tag]
# Required: TRANSFORM_WORKSPACE_ID=<uuid> for deploy runs. Optional: BEDROCK_API_KEY_SECRET_ARN, TRANSFORM_ORCHESTRATOR_AGENT,
# TRANSFORM_ROLE_ARN (+ TRANSFORM_EXTERNAL_ID), DEPLOY_ASSUME_ROLE_ARN (target-role pattern; default IngramLandingZoneDeploy*).
set -euo pipefail
cd "$(dirname "$0")/.."

CODE_BUCKET=${1:?existing S3 bucket for code}; DOMAIN=${2:?cognito domain prefix}; MODEL=${3:?bedrock model/inference-profile id}
TAG=${4:-}
STACK="${CFN_STACK:-lz-agent}"
PROJECT="${PROJECT_NAME:-lz-agent}"

echo "Packaging Lambdas (python3.12, linux x86_64 wheels) and buildspecs"
rm -rf build && mkdir -p build/pkg
pip install -q --target build/pkg --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: pypdf python-docx
pip install -q --target build/pkg -r orchestration/requirements.txt
cp orchestration/lambdas/*.py build/pkg/
cp -R lzcore templates build/pkg/
find build/pkg -name __pycache__ -type d -prune -exec rm -rf {} +
(cd build/pkg && zip -qr ../orchestration.zip .)
(cd buildspecs && zip -qr ../build/buildspecs.zip .)
cp orchestration/statemachine.asl.json orchestration/deployment.asl.json build/
for f in orchestration.zip buildspecs.zip statemachine.asl.json deployment.asl.json; do aws s3 cp "build/$f" "s3://$CODE_BUCKET/$f" --only-show-errors; done

IMAGE_URI=""
if [ -n "$TAG" ]; then
  REPO_URI=$(aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='AgentRepoUri'].OutputValue" --output text)
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URI%%/*}"
  docker buildx build --platform linux/arm64 -f agent/Dockerfile -t "$REPO_URI:$TAG" --push .
  IMAGE_URI="$REPO_URI:$TAG"
fi
if [ -z "$IMAGE_URI" ]; then
  IMAGE_URI=$(aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Parameters[?ParameterKey=='AgentImageUri'].ParameterValue | [0]" --output text 2>/dev/null || true)
  if [ "$IMAGE_URI" = "None" ] || [ -z "$IMAGE_URI" ]; then IMAGE_URI=""; fi
fi

: "${TRANSFORM_WORKSPACE_ID:?set TRANSFORM_WORKSPACE_ID (AWS Transform workspace UUID) before deploy}"
ENABLE_CF="${ENABLE_CLOUDFRONT:-true}"
DEPLOY_PARAMS=(ProjectName="$PROJECT" CodeBucket="$CODE_BUCKET" CognitoDomainPrefix="$DOMAIN" ModelId="$MODEL" AgentImageUri="$IMAGE_URI" TransformWorkspaceId="$TRANSFORM_WORKSPACE_ID" EnableCloudFront="$ENABLE_CF")
if [ -n "${AGENT_RUNTIME_ARN:-}" ]; then
  DEPLOY_PARAMS+=(AgentRuntimeArn="$AGENT_RUNTIME_ARN")
fi
if [ -n "${BEDROCK_API_KEY_SECRET_ARN:-}" ]; then
  DEPLOY_PARAMS+=(BedrockApiKeySecretArn="$BEDROCK_API_KEY_SECRET_ARN")
fi
if [ -n "${TRANSFORM_ORCHESTRATOR_AGENT:-}" ]; then
  DEPLOY_PARAMS+=(TransformOrchestratorAgent="$TRANSFORM_ORCHESTRATOR_AGENT")
fi
# Always pass DeployAssumeRoleArn: `cloudformation deploy` keeps a stack's previous value for omitted parameters,
# so a stack created when the default was "*" would otherwise keep "*". Override with DEPLOY_ASSUME_ROLE_ARN.
DEPLOY_PARAMS+=(DeployAssumeRoleArn="${DEPLOY_ASSUME_ROLE_ARN:-arn:aws:iam::*:role/IngramLandingZoneDeploy*}")
# Transform in another account (same AWS Organization as the landing-zone target): role + external id.
# The external id is not a secret (it is a confused-deputy guard), so passing it on the command line is fine.
if [ -n "${TRANSFORM_ROLE_ARN:-}" ]; then
  DEPLOY_PARAMS+=(TransformRoleArn="$TRANSFORM_ROLE_ARN" TransformExternalId="${TRANSFORM_EXTERNAL_ID:-}")
fi
CFN_TAG_ARGS=()
if [ -n "${PROJECT_OWNER_NAME:-}" ]; then
  TAGS=("Key=Owner,Value=${PROJECT_OWNER_NAME}")
  [ -n "${PROJECT_OWNER_EMAIL:-}" ] && TAGS+=("Key=OwnerEmail,Value=${PROJECT_OWNER_EMAIL}")
  [ -n "${PROJECT_DISPLAY_NAME:-}" ] && TAGS+=("Key=ProjectDisplayName,Value=${PROJECT_DISPLAY_NAME}")
  CFN_TAG_ARGS=(--tags "${TAGS[@]}")
fi
if ((${#CFN_TAG_ARGS[@]})); then
  aws cloudformation deploy --stack-name "$STACK" --template-file infra/platform/platform.yaml \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides "${DEPLOY_PARAMS[@]}" \
    "${CFN_TAG_ARGS[@]}"
else
  aws cloudformation deploy --stack-name "$STACK" --template-file infra/platform/platform.yaml \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides "${DEPLOY_PARAMS[@]}"
fi

# CloudFormation does not see a changed zip under the same S3 key, so push the new code to the Zip Lambdas directly
for fn in $(aws cloudformation describe-stack-resources --stack-name "$STACK" --query "StackResources[?ResourceType=='AWS::Lambda::Function'].PhysicalResourceId" --output text); do
  if [ "$(aws lambda get-function-configuration --function-name "$fn" --query PackageType --output text)" = "Zip" ]; then
    aws lambda update-function-code --function-name "$fn" --s3-bucket "$CODE_BUCKET" --s3-key orchestration.zip --query FunctionName --output text
    aws lambda wait function-updated --function-name "$fn"
  fi
done

out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
cat > build/config.json <<EOF
{"apiUrl":"$(out ApiUrl)","clientId":"$(out UserPoolClientId)","cognitoDomain":"$(out CognitoDomain)"}
EOF
UI=$(out UiBucketName)
# no-cache: browsers must revalidate the UI files on every load, or a stale app.js can meet a new index.html (blank page)
sed "s|src=\"app.js\"|src=\"app.js?v=$(date +%s)\"|" ui/index.html > build/index.html  # version the script so a cached app.js cannot meet a new page
aws s3 cp build/index.html "s3://$UI/index.html" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp ui/app.js "s3://$UI/app.js" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp build/config.json "s3://$UI/config.json" --content-type application/json --cache-control no-store --only-show-errors
echo "UI: $(out UiUrl)"
[ -n "$TAG" ] || echo "First pass done. Re-run with an image tag (e.g. v1) to build the agent image and create the AgentCore runtime."
