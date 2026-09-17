# TapInX frontend deployment

The production React dashboard is hosted in the existing S3 bucket and served
through the existing CloudFront distribution. A frontend release must not run
Terraform or create replacement AWS infrastructure.

## Production targets

- Website: `https://tapinx.in`
- S3 bucket: `tapinx-web-portal-532025488693-us-east-1-an`
- CloudFront distribution: `E28VCKLNUS67BA`
- AWS region for the bucket: `us-east-1`

The production build deliberately leaves `VITE_API_URL` empty. The application
then uses `window.location.origin`, so API calls use `https://tapinx.in/api` and
Socket.IO uses `https://tapinx.in/socket.io/` through the existing CloudFront
behaviors.

## Automated deployment

`.github/workflows/deploy-frontend.yml` runs when frontend-related files are
pushed to `aws_deploy`, or when manually started from GitHub Actions. It:

1. installs locked npm dependencies;
2. lints and builds the dashboard;
3. assumes a narrowly scoped AWS IAM role through GitHub OIDC;
4. synchronizes `web-dashboard/dist` to the existing bucket; and
5. invalidates the existing CloudFront distribution.

Create a GitHub environment named `production` and add this environment secret:

- `AWS_FRONTEND_DEPLOY_ROLE_ARN`: ARN of the IAM role GitHub Actions may assume.

The role should trust GitHub's OIDC provider only for this repository's
`production` environment. Configure that GitHub environment to allow deployment
only from the `aws_deploy` branch. The role's permissions should be limited to
listing and updating the production bucket and invalidating distribution
`E28VCKLNUS67BA`. No AWS access keys are stored in GitHub.

The role's permissions policy can be limited to:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::tapinx-web-portal-532025488693-us-east-1-an"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::tapinx-web-portal-532025488693-us-east-1-an/*"
    },
    {
      "Effect": "Allow",
      "Action": ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
      "Resource": "arn:aws:cloudfront::532025488693:distribution/E28VCKLNUS67BA"
    }
  ]
}
```

Its trust policy should restrict the GitHub subject to this repository's
`production` environment:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::532025488693:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:SJDeshmukh/OpenVisionFaceDetector:environment:production"
      }
    }
  }]
}
```

Optional GitHub environment variables `AWS_FRONTEND_BUCKET` and
`AWS_CLOUDFRONT_DISTRIBUTION_ID` can override the checked-in production defaults.

## Manual deployment

With an authenticated AWS CLI, run:

```bash
scripts/deploy-frontend-s3.sh
```

To verify the local build and deployment target without changing AWS:

```bash
scripts/deploy-frontend-s3.sh --dry-run
```

The script gives hashed Vite assets long-lived immutable caching, prevents
`index.html` from being cached by browsers, removes obsolete build artifacts,
and waits until the CloudFront invalidation completes.
