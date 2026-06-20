# CLAUDE.md — Landing Page Project


## Project Overview


A static landing page built with vanilla JavaScript and Bootstrap CSS, deployed to AWS S3 as a static website.

---

## Tech Stack

| Layer       | Technology                        |
|-------------|-----------------------------------|
| Markup      | HTML5                             |
| Styling     | Bootstrap 5 (CDN) + custom CSS    |
| Scripting   | Vanilla JavaScript (ES6+)         |
| Hosting     | AWS S3 Static Website Hosting     |
| Delivery    | (Optional) AWS CloudFront CDN     |

---

## Project Structure

```
/
├── index.html          # Entry point — must be named exactly index.html for S3
├── error.html          # Custom S3 error page (404 / access denied)
├── css/
│   └── styles.css      # Custom styles layered on top of Bootstrap
├── js/
│   └── main.js         # All custom JavaScript
├── assets/
│   ├── images/         # Optimized images (WebP preferred)
│   └── fonts/          # Self-hosted fonts if not using Google Fonts CDN
│   └── logos/          # Optimized images (WebP preferred)
└── CLAUDE.md           # This file
```

---

## Coding Standards

### HTML
- Use semantic HTML5 elements (`<header>`, `<main>`, `<section>`, `<footer>`, `<nav>`, `<article>`).
- Every page must have a unique `<title>` and a `<meta name="description">` tag.
- All images must have descriptive `alt` attributes.
- Bootstrap is loaded via CDN in `<head>`; custom CSS follows after.
- JavaScript is loaded just before `</body>` with `defer` where appropriate.

```html
<!-- Bootstrap CSS — always load before custom styles -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="css/styles.css">

<!-- Scripts before closing </body> -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="js/main.js" defer></script>
```

### CSS (`css/styles.css`)
- Use CSS custom properties (variables) for the design system — colors, spacing, fonts.
- Override Bootstrap variables at the top of the file using `:root {}`.
- Never use `!important` unless absolutely necessary to override a Bootstrap rule.
- Mobile-first: write base styles for small screens, then use Bootstrap breakpoints (`sm`, `md`, `lg`, `xl`) to scale up.
- Class naming: use BEM for custom component classes (`.hero__title`, `.cta-block__button`).

```css
/* Design tokens — define once, use everywhere */
:root {
  --color-primary: #b3dcd3;
  --color-accent: #000000;
  --color-bg: #3a5f62;
  --color-text: #ffffff;
  --font-heading: 'Your Heading Font', serif;
  --font-body: 'Your Body Font', sans-serif;
  --spacing-section: 5rem;
}
```

### JavaScript (`js/main.js`)
- Use ES6+ syntax: `const`/`let`, arrow functions, template literals, optional chaining.
- No jQuery. Use the native DOM API and Bootstrap's JavaScript API.
- Wrap all DOM-dependent code in a `DOMContentLoaded` listener.
- Validate all form inputs client-side before submission.
- Prefer `fetch()` for any async data loading; handle errors explicitly.
- Never commit API keys or secrets — use environment variables injected at build time or a backend proxy.

```js
document.addEventListener('DOMContentLoaded', () => {
  // All DOM logic goes here
});
```

---

## Design Guidelines

- Follow the aesthetic direction established in the design brief (see `assets/` references).
- Typography, color, and spacing should reference the CSS variables above — never hardcode values in component styles.
- Animations: prefer CSS transitions/keyframes; use JS only when CSS cannot achieve the effect.
- Maintain WCAG 2.1 AA contrast ratios for all text on backgrounds.
- Avoid adding new third-party libraries unless explicitly approved — keep the bundle lean for S3 + CloudFront delivery.

---

## AWS S3 Deployment

### Bucket Requirements
- Bucket name must match the domain if using Route 53 (e.g., `www.example.com`).
- Static website hosting must be enabled in the bucket properties.
- **Index document**: `index.html`
- **Error document**: `error.html`
- Block Public Access settings: turn off "Block all public access" for a public site.
- Attach a bucket policy granting public read access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

### File Upload Rules
- All filenames and paths are **case-sensitive** on S3. Use lowercase with hyphens only (e.g., `hero-image.webp`, not `HeroImage.WebP`).
- Set correct `Content-Type` metadata when uploading (S3 does not always infer it automatically).
- Enable gzip compression via CloudFront or pre-compress assets before upload.

### Recommended Deploy Command (AWS CLI)

```bash
# Sync local build to S3, delete removed files, set cache headers
aws s3 sync . s3://YOUR-BUCKET-NAME \
  --exclude ".git/*" \
  --exclude "CLAUDE.md" \
  --exclude "*.md" \
  --exclude "infra/*" \
  --delete \
  --cache-control "max-age=86400, public"

# Set longer cache for hashed static assets (images, fonts)
aws s3 cp assets/ s3://YOUR-BUCKET-NAME/assets/ \
  --recursive \
  --cache-control "max-age=31536000, public, immutable"
```

### CloudFront (Optional but Recommended)
- Create a CloudFront distribution pointing to the S3 static website endpoint (not the S3 REST endpoint).
- Set default root object to `index.html`.
- Create a custom error response: HTTP 403/404 → `/error.html` → 200.
- Invalidate the cache after every deploy: `aws cloudfront create-invalidation --distribution-id YOUR_ID --paths "/*"`

---

## Performance Targets

| Metric                   | Target        |
|--------------------------|---------------|
| Lighthouse Performance   | ≥ 90          |
| First Contentful Paint   | < 1.5 s       |
| Largest Contentful Paint | < 2.5 s       |
| Total Blocking Time      | < 200 ms      |
| Cumulative Layout Shift  | < 0.1         |
| Total page weight        | < 500 KB      |

- Compress all images; use WebP with JPEG fallback.
- Lazy-load below-the-fold images with `loading="lazy"`.
- Load Bootstrap and fonts from CDN to leverage browser caching.
- Keep custom JS minimal and defer non-critical scripts.

---

## Accessibility

- All interactive elements must be keyboard-navigable.
- Use ARIA attributes where semantic HTML alone is insufficient.
- Test with a screen reader (NVDA, VoiceOver) before shipping.
- Color contrast: minimum 4.5:1 for body text, 3:1 for large text.

---

## Environment & Secrets

- **Never** commit AWS credentials, API keys, or tokens to the repository.
- Use AWS IAM roles with least-privilege permissions for deployment.
- Store secrets in environment variables or AWS Secrets Manager.
- Use `.gitignore` to exclude `.env` files and AWS credential files.

---

## Common Pitfalls to Avoid

1. **Wrong S3 endpoint type** — use the *website* endpoint (`http://bucket.s3-website-region.amazonaws.com`), not the REST endpoint, when configuring CloudFront or testing redirects.
2. **Case-sensitive paths** — S3 treats `/About` and `/about` as different objects. Standardize on lowercase.
3. **Missing Content-Type** — always set `Content-Type: text/html` on `.html` files and `text/css` on `.css` files when uploading via CLI.
4. **Bootstrap JS not loading** — `bootstrap.bundle.min.js` includes Popper.js; don't load Popper separately.
5. **Hardcoded absolute paths** — use root-relative paths (`/css/styles.css`) so the site works on both localhost and S3.
6. **CORS issues** — if the page fetches an external API, ensure CORS headers are configured on that API, not on S3.
