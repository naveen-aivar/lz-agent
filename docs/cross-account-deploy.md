# Cross-account deploy target

Deploy runs can target an AWS account other than the platform account. The UI collects a **12-digit account id** plus either:

- **IAM role (recommended)**: the platform calls `sts:AssumeRole` into a role in the target account. An **external ID is required**.
- **Access keys**: stored encrypted for this deploy run only and deleted when the run ends (details below). Long-lived `AKIA…` keys are accepted, but prefer role mode or short-lived session credentials (`ASIA…` + session token).

Organizations **discover** and **attestation** use the target credentials. **AWS Transform** jobs use the stack's Transform identity and `TransformWorkspaceId` (see [deployment-agent-transform.md](./deployment-agent-transform.md)).

## Target account role

1. Create a role in the target account whose name matches the platform stack's `DeployAssumeRoleArn` pattern (default `arn:aws:iam::*:role/IngramLandingZoneDeploy*`), e.g. `IngramLandingZoneDeploy`, with org/Control Tower read (and whatever Transform/apply needs in your tenant).

2. Trust policy. Two platform roles assume it: **ApiRole** for *Test connection* (`POST /deploy-target/verify`) and **AgentRole** for discover/attest. Use the role ARNs from the platform stack's resources:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": [
      "arn:aws:iam::<platform-account-id>:role/<stack>-AgentRole-<suffix>",
      "arn:aws:iam::<platform-account-id>:role/<stack>-ApiRole-<suffix>"
    ] },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "<external-id>" } }
  }]
}
```

   The external ID is a confused-deputy guard, not a secret. Pick a unique value per customer; the platform refuses role mode without one.

3. If the role name does not match the default pattern, deploy the platform with `DEPLOY_ASSUME_ROLE_ARN=<pattern>` (`scripts/deploy.sh` always passes `DeployAssumeRoleArn`, because `cloudformation deploy` would otherwise keep a stack's previous value, which was `*` on older stacks). Never set it to `*`.

4. In the UI: **Start deploy run** → target account id, role ARN, external ID.

## Access keys: storage and lifetime

- Stored at `deploy-target-credentials/{deployRunId}.json` in the artifact bucket, outside `runs/*`, with SSE-KMS under the **stack CMK** (`SSEKMSKeyId` set explicitly; the bucket policy denies writes under that prefix with any other key).
- Readers: only **AgentRole**. IAM grants nothing else `GetObject` on the prefix, and the bucket policy denies `GetObject`/`GetObjectVersion` there to every other principal, account admins included. ApiRole may write and delete; PhaseRole may delete.
- Deleted (every version, since the bucket is versioned) when the run is **DELIVERED** or **FAILED** (`phase_deploy_status`) and on **`/stop`**. A failed delete is recorded in `META.credentialsCleanupError`, audited (`deploy.target_credentials_delete_failed`) and surfaced: `/stop` returns 500, and the state machine task fails. Rotate the key and delete the object by hand in that case.
- Backstop: a lifecycle rule expires the prefix after 4 days (noncurrent versions after 1 more day) for executions that end without reaching `MarkFailed`, e.g. the 72 h execution timeout.
- Runs created before this change stored keys under `runs/{deployRunId}/deployment/target-credentials.json`. Those objects are not touched by the new cleanup; delete every version of them manually.
- `META.deployTarget.credentialsKey` points to the object. API responses and audit rows show `deployTarget` as `{mode, accountId, roleArn}` only.

## Test credentials (before deploy)

```http
POST /deploy-target/verify
Content-Type: application/json

{
  "designRunId": "<delivered-design-run-id>",
  "deployTarget": {
    "accountId": "<target-account-id>",
    "roleArn": "arn:aws:iam::<target-account-id>:role/IngramLandingZoneDeploy",
    "externalId": "<external-id>"
  }
}
```

`designRunId` must be a **DELIVERED** design run owned by the caller (404 when it is missing or not yours, 409 when it is not DELIVERED), so the endpoint is not an open AssumeRole or key-validity oracle. Same `deployTarget` shape as deploy (role or keys). Secrets are **not** stored; the API runs STS `GetCallerIdentity` and a read-only Organizations probe. The result is `ok: false` when the credentials fail **or** the Organizations probe errors (the message names the error); "not enabled" and "access denied" come back as warnings. The UI **Test connection** button calls this endpoint.

## API

```http
POST /runs/{designRunId}/deploy
Content-Type: application/json

{
  "deployTarget": {
    "accountId": "<target-account-id>",
    "roleArn": "arn:aws:iam::<target-account-id>:role/IngramLandingZoneDeploy",
    "externalId": "<external-id>"
  }
}
```

Omit `deployTarget` (or use auth method "Platform account only") for the previous single-account behavior.

## Operator-started runs (`scripts/run_deploy.py`)

The script invokes the api-runs Lambda directly (IAM-gated by `lambda:InvokeFunction`), so there is no Cognito token. The run is owned by the design run's requester so it appears in their Runs list, and the operator's IAM ARN from `sts get-caller-identity` is sent as `invokedBy`. `api_runs` honors `invokedBy` only when the event has no `requestContext.http` (a direct invoke), requires it on direct invokes, and rejects it on API Gateway events. It is stored in `META.invokedBy` and in the `deploy.started`, `design.deploy_requested` and `run.stopped` audit details. The value is asserted by the caller; CloudTrail's `Invoke` event is the authoritative record of which principal called the function.
