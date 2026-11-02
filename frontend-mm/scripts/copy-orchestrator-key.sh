#!/usr/bin/env bash
# Copies the deck orchestrator's access key into this account's Secrets Manager, where its key gate reads it.
#   scripts/copy-orchestrator-key.sh                  a dry run: checks both accounts and the source secret, copies nothing
#   APPLY=1 scripts/copy-orchestrator-key.sh         does it
# The key goes straight from one aws command to the other (the line break that `--output text` adds is removed: a key with a
# line break is an invalid header). It is never printed, never written to a file, never put in the
# command line (so not in the process list or the shell history).
# Settings: SOURCE_PROFILE (default ai-ml-831493647146), SOURCE_SECRET (default mm-dev/access-key), TARGET_PROFILE (default
# arun-doc-ex), TARGET_SECRET (default ingram-mm-dashboard/orchestrator-access-key).
set -euo pipefail
export AWS_PAGER="" AWS_DEFAULT_REGION=us-east-1
SOURCE_PROFILE="${SOURCE_PROFILE:-ai-ml-831493647146}"
SOURCE_SECRET="${SOURCE_SECRET:-mm-dev/access-key}"
TARGET_PROFILE="${TARGET_PROFILE:-arun-doc-ex}"
TARGET_SECRET="${TARGET_SECRET:-ingram-mm-dashboard/orchestrator-access-key}"
SOURCE_ACCOUNT="831493647146"
TARGET_ACCOUNT="455162169375"
log() { printf '[copy-key] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

account_of() { aws sts get-caller-identity --profile "$1" --query Account --output text 2>/dev/null || die "cannot call AWS with profile $1 (try: aws sso login --profile $1)"; }
FOUND="$(account_of "$SOURCE_PROFILE")" || exit 1
[ "$FOUND" = "$SOURCE_ACCOUNT" ] || die "profile $SOURCE_PROFILE is not account $SOURCE_ACCOUNT"
FOUND="$(account_of "$TARGET_PROFILE")" || exit 1
[ "$FOUND" = "$TARGET_ACCOUNT" ] || die "profile $TARGET_PROFILE is not account $TARGET_ACCOUNT"
aws secretsmanager describe-secret --profile "$SOURCE_PROFILE" --secret-id "$SOURCE_SECRET" --query Name --output text >/dev/null 2>&1 \
  || die "the source secret $SOURCE_SECRET does not exist in account $SOURCE_ACCOUNT"
if aws secretsmanager describe-secret --profile "$TARGET_PROFILE" --secret-id "$TARGET_SECRET" --query Name --output text >/dev/null 2>&1; then
  ACTION="update"; else ACTION="create"; fi
log "would $ACTION $TARGET_SECRET in account $TARGET_ACCOUNT from $SOURCE_SECRET in account $SOURCE_ACCOUNT"
if [ "${APPLY:-0}" != "1" ]; then log "DRY RUN: nothing was copied (APPLY=1 copies)."; exit 0; fi

if [ "$ACTION" = "create" ]; then
  aws secretsmanager get-secret-value --profile "$SOURCE_PROFILE" --secret-id "$SOURCE_SECRET" --query SecretString --output text \
    | tr -d '\r\n' \
    | aws secretsmanager create-secret --profile "$TARGET_PROFILE" --name "$TARGET_SECRET" \
        --description "Access key of the deck orchestrator API, read only by its dashboard key gate" \
        --secret-string file:///dev/stdin --query Name --output text >/dev/null
else
  aws secretsmanager get-secret-value --profile "$SOURCE_PROFILE" --secret-id "$SOURCE_SECRET" --query SecretString --output text \
    | tr -d '\r\n' \
    | aws secretsmanager put-secret-value --profile "$TARGET_PROFILE" --secret-id "$TARGET_SECRET" \
        --secret-string file:///dev/stdin --query Name --output text >/dev/null
fi
log "done: $TARGET_SECRET now holds the key (not shown)."
