# DJ Johnny Denver — Landing Page & Serverless Booking Backend

A **production**, fully responsive marketing site for a professional event DJ, backed by a serverless booking pipeline on AWS. The front end is hand-built with semantic HTML, Bootstrap 5, and dependency-free vanilla JavaScript; the booking form is wired to an API Gateway → Lambda → DynamoDB + SES backend with input validation, anti-spam, rate limiting, and CloudWatch alerting.

🔗 **Live site:** https://djjohnnydenver.com

> The site is localized in Spanish (`es-419`) for its Denver-area Latino audience — the content language is intentional, not a placeholder.

---

## Architecture

```
                          ┌─────────────────────────────────────────────┐
   Browser                │                    AWS                       │
   ┌──────────┐           │                                              │
   │ index.html│  HTTPS   │  ┌───────────┐   Route 53 (DNS)              │
   │  + JS/CSS │◀─────────┼──│ CloudFront│◀── ACM (TLS cert)             │
   └────┬─────┘  (static) │  │   (CDN)   │──▶ S3 (static website bucket) │
        │                 │  └───────────┘                               │
        │ POST /booking   │                                              │
        │ (JSON, fetch)   │  ┌─────────────┐   ┌────────┐                │
        └─────────────────┼─▶│ API Gateway │──▶│ Lambda │──┬─▶ DynamoDB  │
                          │  │  (HTTP API) │   │(Python)│  │  (bookings) │
                          │  │  throttled  │   └────────┘  └─▶ SES (email)│
                          │  └─────────────┘                             │
                          └─────────────────────────────────────────────┘
```

The static assets are served globally via CloudFront over HTTPS; the booking form `POST`s JSON to a throttled HTTP API that triggers a Lambda. The Lambda **stores the lead in DynamoDB first** (durable record), then emails the details to the owner via SES — so a lead is never lost even if the email step fails.

---

## Tech Stack

| Layer        | Technology |
|--------------|------------|
| Markup       | Semantic HTML5 |
| Styling      | Bootstrap 5 (CDN) + custom CSS with design-token variables |
| Scripting    | Vanilla JavaScript (ES6+) — no jQuery, no build step |
| Compute      | AWS Lambda (Python 3.13) |
| API          | API Gateway (HTTP API) with CORS + throttling |
| Data         | Amazon DynamoDB (on-demand) |
| Email        | Amazon SES (v2) |
| Hosting      | S3 static website + CloudFront CDN + ACM (TLS) + Route 53 |
| Monitoring   | CloudWatch log metric filters, alarms, and SNS email alerts |
| Region       | `us-west-2` |

---

## Highlights

### Front end
- **Hand-written, dependency-free JavaScript** — scroll-triggered reveal animations via `IntersectionObserver`, a procedurally generated animated audio-equalizer hero, smooth-scroll navigation, and a mobile nav that collapses on selection.
- **Accessibility first** — semantic landmarks, ARIA labels, keyboard-navigable controls, and WCAG AA contrast targets.
- **Performance-minded** — CDN-loaded Bootstrap/fonts, `defer`ed scripts, lazy-loaded imagery, and a lean asset budget for fast first paint.
- **Mobile-first responsive** design built on a custom CSS design-token system (colors, spacing, typography defined once in `:root`).

### Booking backend
- **Defense in depth on input** — the browser validates for UX, and the Lambda **re-validates everything server-side**: required fields, email/date regex, an allow-list of event types, and per-field length caps that keep every item well under DynamoDB's 400 KB limit.
- **Anti-spam honeypot** — a hidden field real users never touch; bot submissions get a fake `200` (so the bot sees no signal) while nothing is stored or emailed.
- **Store-then-notify ordering** — the booking is persisted to DynamoDB *before* the email is sent, so a lead is never lost to an SES hiccup.
- **Email deliverability done right** — sends `From` a domain identity (passes SPF/DKIM/DMARC) with the customer as `Reply-To`, deliberately avoiding the `DMARC p=reject` failure of sending *as* a free-mail address.

### Security & operations
- **Least-privilege IAM** — a scoped execution-role policy (`infra/iam-policy.json`) granting only the DynamoDB and SES actions the function needs, with a documented `ses:FromAddress` condition that survives the SES sandbox → production transition.
- **Edge rate limiting** — the public, unauthenticated endpoint is throttled at the API Gateway stage so a bot can't run up SES/DynamoDB cost or flood the inbox; excess requests get a `429` before they ever reach the Lambda.
- **Thoughtful alerting** — CloudWatch alarms distinguish *handled* failures (a lead stored but not emailed, surfaced via a log metric filter) from *unhandled* crashes (timeouts/OOM via the Lambda `Errors` metric), routed to an SNS email subscription. The reasoning behind each alarm is documented in `infra/README.md`.
- **CORS locked to the production origin**, not `*`.

### Testing
- **19 unit tests** for the Lambda handler (`infra/lambda/test_lambda_function.py`), with the DynamoDB and SES clients mocked so the suite runs offline with zero AWS access.

---

## Project Structure

```
.
├── index.html                       # Single-page site (hero, about, services, gallery, contact)
├── error.html                       # Branded 404 / error page
├── css/
│   └── styles.css                   # Custom styles + design tokens layered on Bootstrap
├── js/
│   └── main.js                      # All site interactivity + booking-form submit
├── images/                          # Gallery & content imagery
├── logos/                           # Brand logos
└── infra/                           # Serverless booking backend
    ├── README.md                    # Full, reproducible AWS setup runbook
    ├── iam-policy.json              # Least-privilege Lambda execution policy
    └── lambda/
        ├── lambda_function.py       # The booking handler
        ├── requirements.txt
        └── test_lambda_function.py  # 19 unit tests (AWS mocked)
```

---

## Running Locally

The site is fully static — no build step. Serve the root directory with any static server:

```bash
# Python
python -m http.server 8000
# or Node
npx serve .
```

Then open http://localhost:8000.

> The booking form `POST`s to the live API Gateway endpoint, so submitting from `localhost` will be blocked by CORS (which is scoped to the production origin). Point `BOOKING_API_URL` in `js/main.js` at a dev endpoint to exercise the form locally.

### Run the backend tests

```bash
cd infra/lambda
python -m unittest test_lambda_function -v
# or
pytest test_lambda_function.py
```

### Deploy the backend

The complete, copy-pasteable AWS setup — DynamoDB table, SES identities, IAM role, Lambda, HTTP API, throttling, and CloudWatch alarms — lives in [`infra/README.md`](infra/README.md).

---

## Skills Demonstrated

- **Frontend engineering** without a framework: the DOM API, modern ES6+, accessibility, responsive/mobile-first CSS, and performance optimization.
- **Serverless / cloud architecture** on AWS: Lambda, API Gateway, DynamoDB, SES, S3, CloudFront, ACM, Route 53.
- **Security engineering**: server-side validation, anti-abuse (honeypot + rate limiting), least-privilege IAM, CORS, and email-auth (SPF/DKIM/DMARC).
- **Operational maturity**: monitoring, metric-based alarming that reflects real failure modes, and a reproducible infrastructure runbook.
- **Testing discipline**: isolated, mock-based unit tests that run anywhere.
- **Engineering judgment**: the trade-offs and edge cases behind each decision are documented inline rather than left implicit.
