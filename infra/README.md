# Booking backend — API Gateway → Lambda → DynamoDB + SES

Serverless handler for the `booking-form` on the landing page. The browser
`POST`s the form as JSON to an API Gateway URL; the Lambda stores the booking
in DynamoDB and emails the details to DJ Johnny via SES.

```
booking-form ──POST JSON──▶ API Gateway (HTTP API) ──▶ Lambda ──┬──▶ DynamoDB (chupon-bookings)
     ▲                                                          └──▶ SES (email notification)
     └────────────────────── JSON response ◀──────────────────────────┘
```

Files:
- `lambda/lambda_function.py` — the handler (Python 3.13, handler = `lambda_function.handler`)
- `iam-policy.json` — least-privilege policy for the Lambda execution role

> **Email roles (Option A).** `From` = `bookings@djjohnnydenver.com` (a domain you
> control, so it passes SPF/DKIM/DMARC). `To` = `djjohnny74@yahoo.com` (the inbox
> Johnny reads). `Reply-To` = the customer, so replying reaches them directly.
> Sending *from* a `@yahoo.com` address through SES would fail Yahoo's
> `DMARC p=reject` policy — that's why the sender is the domain address.

---

## One-time setup

Set your region/account once for the commands below:

```bash
export AWS_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

### 1. DynamoDB table

```bash
aws dynamodb create-table \
  --table-name chupon-bookings \
  --attribute-definitions AttributeName=id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "$AWS_REGION"
```

### 2. SES — verify the sender domain and the recipient

```bash
# Verify the sender DOMAIN (gives you DKIM records to add to DNS — passes DMARC)
aws sesv2 create-email-identity --email-identity djjohnnydenver.com --region "$AWS_REGION"

# Add the returned CNAME/DKIM records to the djjohnnydenver.com DNS zone.

# While SES is in the sandbox you may only send to verified recipients,
# so verify Johnny's inbox too (one-time click on the confirmation email):
aws sesv2 create-email-identity --email-identity djjohnny74@yahoo.com --region "$AWS_REGION"
```

> The sandbox is fine here — you only ever email one fixed recipient. You do
> **not** need to request production access unless you later email customers directly.

### 3. IAM role for the Lambda

```bash
# Trust policy so Lambda can assume the role
cat > trust.json <<'JSON'
{ "Version": "2012-10-17", "Statement": [{ "Effect": "Allow",
  "Principal": { "Service": "lambda.amazonaws.com" }, "Action": "sts:AssumeRole" }] }
JSON

aws iam create-role --role-name chupon-booking-lambda \
  --assume-role-policy-document file://trust.json

# CloudWatch Logs (managed) + our least-privilege DynamoDB/SES policy
aws iam attach-role-policy --role-name chupon-booking-lambda \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Edit infra/iam-policy.json first: replace REGION and ACCOUNT_ID
aws iam put-role-policy --role-name chupon-booking-lambda \
  --policy-name booking-ddb-ses --policy-document file://iam-policy.json
```

> **Why `ses:SendEmail` is scoped to `identity/*` (not just the sender domain).**
> In the SES **sandbox**, `SendEmail` is authorized against the *recipient*
> identity too — so a policy that only grants the sender domain
> (`identity/djjohnnydenver.com`) fails with `AccessDeniedException` on
> `identity/<recipient>`. We grant `identity/*` but pin the sender with a
> `ses:FromAddress` condition, so the Lambda can still only send **as**
> `bookings@djjohnnydenver.com`. This also survives the move to production
> access (where recipients aren't identities at all). Don't "tighten" the
> Resource back to a single identity or sandbox sends break again.

### 4. Deploy the Lambda

```bash
cd infra/lambda
zip function.zip lambda_function.py

aws lambda create-function \
  --function-name chupon-booking \
  --runtime python3.13 \
  --handler lambda_function.handler \
  --role arn:aws:iam::${ACCOUNT_ID}:role/chupon-booking-lambda \
  --zip-file fileb://function.zip \
  --environment "Variables={TABLE_NAME=chupon-bookings,FROM_ADDRESS=bookings@djjohnnydenver.com,TO_ADDRESS=djjohnny74@yahoo.com,ALLOW_ORIGIN=https://djjohnnydenver.com}" \
  --region "$AWS_REGION"

# To ship code changes later:
#   zip function.zip lambda_function.py
#   aws lambda update-function-code --function-name chupon-booking --zip-file fileb://function.zip
```

### 5. API Gateway (HTTP API) + CORS

```bash
# Create the HTTP API wired straight to the Lambda
aws apigatewayv2 create-api \
  --name chupon-booking-api \
  --protocol-type HTTP \
  --target arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:chupon-booking \
  --cors-configuration AllowOrigins=https://djjohnnydenver.com,AllowMethods=POST,OPTIONS,AllowHeaders=Content-Type \
  --region "$AWS_REGION"

# Allow API Gateway to invoke the function
aws lambda add-permission \
  --function-name chupon-booking \
  --statement-id apigw-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --region "$AWS_REGION"
```

`create-api` prints an `ApiEndpoint` like
`https://abc123.execute-api.us-east-1.amazonaws.com` (and an `ApiId`).

### 5b. Throttle the endpoint (abuse cap)

This is a public, unauthenticated endpoint. Cap the request rate on the
auto-created `$default` stage so a bot can't run up SES/DynamoDB cost or flood
the inbox. A booking form needs only a trickle, so keep the limits low:

```bash
# Use the ApiId printed by create-api above
aws apigatewayv2 update-stage \
  --api-id <API_ID> \
  --stage-name '$default' \
  --default-route-settings ThrottlingRateLimit=5,ThrottlingBurstLimit=10 \
  --region "$AWS_REGION"
```

`ThrottlingRateLimit` is steady-state requests/sec; `ThrottlingBurstLimit` is the
bucket size. Excess requests get a `429` at the edge — they never reach the
Lambda. The in-code honeypot + length caps are the second layer behind this.

### 6. Wire the front end

Put that endpoint in `js/main.js` — set `BOOKING_API_URL` near the top of the
booking-form block. It's a public URL (no secret), so it's safe to commit.

```js
const BOOKING_API_URL = 'https://abc123.execute-api.us-east-1.amazonaws.com';
```

### 7. Monitoring & alerts (CloudWatch)

The handler stores the booking *before* it emails Johnny, so a lead is never
lost — but if the SES send then fails (`BOOKING_EMAIL_FAILED`), the row is in
DynamoDB while Johnny's inbox gets nothing. Johnny reads email, not CloudWatch,
so that lead would be invisible. These alarms email you when that happens.

> **Why not just alarm on the Lambda `Errors` metric?** Because the handler
> *catches* the failure and returns a clean `500`, so Lambda counts the
> invocation as a success — `AWS/Lambda Errors` would never fire for the
> stored-but-not-emailed case. We watch the log markers instead, and keep an
> `Errors` alarm only for *unhandled* crashes (timeouts, OOM, bad deploys).

```bash
# Where alerts go — set to whoever maintains the site (NOT a customer).
ALERT_EMAIL=you@example.com

# 1. SNS topic + email subscription (click the confirmation email once to arm it)
ALERT_TOPIC_ARN=$(aws sns create-topic --name chupon-booking-alerts \
  --query TopicArn --output text --region "$AWS_REGION")

aws sns subscribe --topic-arn "$ALERT_TOPIC_ARN" \
  --protocol email --notification-endpoint "$ALERT_EMAIL" \
  --region "$AWS_REGION"

# 2. Log metric filter: count the handler's failure markers in the log group.
#    (The log group is created automatically on the function's first invocation.)
aws logs put-metric-filter \
  --log-group-name /aws/lambda/chupon-booking \
  --filter-name booking-handled-errors \
  --filter-pattern '?BOOKING_EMAIL_FAILED ?BOOKING_PUT_FAILED' \
  --metric-transformations \
      metricName=BookingHandledErrors,metricNamespace=Chupon/Booking,metricValue=1,defaultValue=0 \
  --region "$AWS_REGION"

# 3a. Alarm on those handled failures (the stored-but-not-emailed case)
aws cloudwatch put-metric-alarm \
  --alarm-name chupon-booking-handled-errors \
  --alarm-description "Booking handler logged a PUT/EMAIL failure — check DynamoDB for an un-emailed lead" \
  --namespace Chupon/Booking --metric-name BookingHandledErrors \
  --statistic Sum --period 300 --evaluation-periods 1 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$ALERT_TOPIC_ARN" --region "$AWS_REGION"

# 3b. Alarm on UNHANDLED failures (timeouts, OOM, runtime crashes)
aws cloudwatch put-metric-alarm \
  --alarm-name chupon-booking-lambda-errors \
  --alarm-description "Booking Lambda threw an unhandled error (crash/timeout)" \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=chupon-booking \
  --statistic Sum --period 300 --evaluation-periods 1 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$ALERT_TOPIC_ARN" --region "$AWS_REGION"
```

When `chupon-booking-handled-errors` fires, find the un-emailed lead in the
logs and DynamoDB:

```bash
aws logs filter-log-events --log-group-name /aws/lambda/chupon-booking \
  --filter-pattern BOOKING_EMAIL_FAILED --region "$AWS_REGION"
# each match prints `id=<uuid>` — look that id up in the chupon-bookings table.
```

### 8. GitHub Actions OIDC (CI/CD)

Lets the workflows in `.github/workflows/` deploy without any long-lived AWS
credentials stored in GitHub. GitHub mints a short-lived OIDC token per run and
AWS trades it for temporary credentials — nothing to rotate, nothing to leak.

```bash
# The OIDC identity provider (one per account — reuse it if it already exists)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com

# Edit both policy files first: replace ACCOUNT_ID, REGION, and DISTRIBUTION_ID
aws iam create-role --role-name chupon-gha-deploy \
  --assume-role-policy-document file://infra/github-oidc-trust-policy.json

aws iam put-role-policy --role-name chupon-gha-deploy \
  --policy-name chupon-gha-deploy \
  --policy-document file://infra/github-oidc-deploy-policy.json
```

Then point the workflows at it with GitHub **variables** (not secrets — none of
these are credentials, and variables keep account IDs out of a public repo):

```bash
gh variable set AWS_ROLE_ARN --body "arn:aws:iam::${ACCOUNT_ID}:role/chupon-gha-deploy"
gh variable set AWS_REGION --body "us-west-2"
gh variable set S3_BUCKET --body "djjohnnydenver.com"
gh variable set CLOUDFRONT_DISTRIBUTION_ID --body "YOUR_DISTRIBUTION_ID"
```

> **The trust policy is the security boundary, not the permissions policy.**
> `github-oidc-trust-policy.json` pins `sub` to
> `repo:cesar1/dj-johnny-denver:ref:refs/heads/main`, so only workflow runs on
> *this repo's main branch* can assume the role — a fork, a PR branch, or another
> repo entirely all fail at `AssumeRoleWithWebIdentity`. If you ever want deploys
> from a second branch or a tag, that string is the thing to widen; loosening it
> to a wildcard would let any repo on GitHub assume the role.

> **Every workflow that assumes this role needs `permissions: id-token: write`.**
> Omitting it is the most common failure mode and surfaces as the misleading
> `Credentials could not be loaded` from `configure-aws-credentials`.

---

## Important: keep `infra/` and `.github/` out of the S3 site

The site deploy runs `aws s3 sync . s3://…` from the repo root, which without
excludes would publish this `infra/` folder — and the `.github/` workflows — to
the public website.

Both are already excluded in `.github/workflows/deploy-site.yml`, which is the
canonical deploy path; the block in the root `CLAUDE.md` is the manual fallback
and carries the same list. **If you add an exclude to one, add it to the other.**

> `--exclude` also protects a file from `--delete`. Adding an exclude does *not*
> remove what is already in the bucket — clear it once with `aws s3 rm`.

## Testing

```bash
# Hit the live endpoint
curl -i -X POST https://abc123.execute-api.us-east-1.amazonaws.com \
  -H 'Content-Type: application/json' \
  -d '{"name":"Prueba","email":"test@example.com","event_date":"2026-08-01","event_type":"wedding"}'

# Tail the logs
aws logs tail /aws/lambda/chupon-booking --follow --region "$AWS_REGION"
```
