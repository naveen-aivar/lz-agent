# Cross-account deploy target

Deploy runs can target an AWS account other than the platform account. The UI collects a **12-digit account id** plus either:

- **IAM role (recommended)** — platform AgentCore role calls `sts:AssumeRole` into a role in the target account, or  
- **Temporary access keys** — stored encrypted in the artifact bucket for the deploy run only (not returned by the API).

Organizations **discover** and **attestation** use the target credentials. **AWS Transform** jobs still use SigV4 from the **platform** account and the stack’s `TransformWorkspaceId` until Transform is configured for the target org.

## Target account role (example for `556880010183`)

1. Create role `IngramLandingZoneDeploy` in the target account with org/Control Tower read (and whatever Transform/apply needs in your tenant).

2. Trust policy (replace `831493647146` with your **platform** account id and `AgentRole` name from CloudFormation):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::831493647146:role/ingram-landing-zone-AgentRole-XXXXXXXX" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "your-external-id" } }
  }]
}
```

3. Platform stack parameter `DeployAssumeRoleArn` must allow assuming that role (default `*`).

4. In the UI: **Start deploy run** → target account `556880010183`, role ARN, optional external id.

## Test credentials (before deploy)

```http
POST /deploy-target/verify
Content-Type: application/json

{
  "deployTarget": {
    "accountId": "556880010183",
    "accessKeyId": "...",
    "secretAccessKey": "...",
    "sessionToken": "optional"
  }
}
```

Same shape as deploy (role or keys). Secrets are **not** stored; the API runs STS `GetCallerIdentity` and a read-only Organizations probe. The UI **Test connection** button calls this endpoint.

## API

```http
POST /runs/{designRunId}/deploy
Content-Type: application/json

{
  "deployTarget": {
    "accountId": "556880010183",
    "roleArn": "arn:aws:iam::556880010183:role/IngramLandingZoneDeploy",
    "externalId": "optional"
  }
}
```

Omit `deployTarget` (or use auth method “Platform account only”) for the previous single-account behavior.
