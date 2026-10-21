#!/usr/bin/env bash
# Deploys the PLATFORM into the account/region of your current AWS credentials. Creates real resources: review first.
# Usage: scripts/deploy.sh <code-bucket> <cognito-domain-prefix> <bedrock-model-id> [image-tag]
set -euo pipefail
cd "$(dirname "$0")/.."

CODE_BUCKET=${1:?existing S3 bucket for code}; DOMAIN=${2:?cognito domain prefix}; MODEL=${3:?bedrock model/inference-profile id}
TAG=${4:-}
# CloudFormation stack name (console). Override with CFN_STACK. ProjectName sets Lambda/DynamoDB/etc. prefixes; override with PROJECT_NAME.
STACK="${CFN_STACK:-naveen-landing-zone}"
PROJECT="${PROJECT_NAME:-naveen-landing-zone}"

echo "Packaging Lambdas (python3.12, linux x86_64 wheels) and buildspecs"
rm -rf build && mkdir -p build/pkg
pip install -q --target build/pkg --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: pypdf python-docx
cp orchestration/lambdas/*.py build/pkg/
cp -R lzcore templates build/pkg/
find build/pkg -name __pycache__ -type d -prune -exec rm -rf {} +
(cd build/pkg && zip -qr ../orchestration.zip .)
(cd buildspecs && zip -qr ../build/buildspecs.zip .)
cp orchestration/statemachine.asl.json build/
for f in orchestration.zip buildspecs.zip statemachine.asl.json; do aws s3 cp "build/$f" "s3://$CODE_BUCKET/$f" --only-show-errors; done

IMAGE_URI=""
if [ -n "$TAG" ]; then
  REPO_URI=$(aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='AgentRepoUri'].OutputValue" --output text)
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URI%%/*}"
  docker buildx build --platform linux/arm64 -f agent/Dockerfile -t "$REPO_URI:$TAG" --push .
  IMAGE_URI="$REPO_URI:$TAG"
fi

aws cloudformation deploy --stack-name "$STACK" --template-file infra/platform/platform.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides ProjectName="$PROJECT" CodeBucket="$CODE_BUCKET" CognitoDomainPrefix="$DOMAIN" ModelId="$MODEL" AgentImageUri="$IMAGE_URI"

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
