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

---

## Important: keep `infra/` out of the S3 site

The deploy command in the root `CLAUDE.md` runs `aws s3 sync . s3://…`, which would
upload this `infra/` folder to the public website. Add an exclude:

```bash
aws s3 sync . s3://YOUR-BUCKET-NAME \
  --exclude ".git/*" \
  --exclude "CLAUDE.md" \
  --exclude "*.md" \
  --exclude "infra/*" \      # ← add this
  --delete \
  --cache-control "max-age=86400, public"
```

## Testing

```bash
# Hit the live endpoint
curl -i -X POST https://abc123.execute-api.us-east-1.amazonaws.com \
  -H 'Content-Type: application/json' \
  -d '{"name":"Prueba","email":"test@example.com","event_date":"2026-08-01","event_type":"wedding"}'

# Tail the logs
aws logs tail /aws/lambda/chupon-booking --follow --region "$AWS_REGION"
```
