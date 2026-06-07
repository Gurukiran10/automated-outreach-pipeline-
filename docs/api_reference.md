# API Reference

## Ocean.io

**Purpose:** Find lookalike companies for a seed domain.

**Auth:** `Authorization: Bearer <OCEAN_API_KEY>`

### POST /lookalikes

```bash
curl -X POST https://api.ocean.io/v1/lookalikes \
  -H "Authorization: Bearer $OCEAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "stripe.com",
    "limit": 10
  }'
```

**Response:**
```json
{
  "companies": [
    {
      "domain": "adyen.com",
      "name": "Adyen",
      "industry": "Fintech",
      "employee_count": 3500,
      "country": "NL",
      "similarity_score": 0.91
    }
  ],
  "total": 143
}
```

---

## Prospeo

**Purpose:** Find decision-makers and their emails for a company domain.

**Auth:** `X-KEY: <PROSPEO_API_KEY>`

### POST /domain-search

```bash
curl -X POST https://api.prospeo.io/domain-search \
  -H "X-KEY: $PROSPEO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "company": "adyen.com",
    "limit": 5,
    "offset": 0
  }'
```

**Response:**
```json
{
  "response": {
    "email_list": [
      {
        "first_name": "John",
        "last_name": "Doe",
        "full_name": "John Doe",
        "title": "CEO",
        "linkedin_url": "https://linkedin.com/in/johndoe",
        "company": "Adyen",
        "email": { "value": "john@adyen.com", "status": "verified" }
      }
    ],
    "total": 147
  }
}
```

---

## EazyReach

**Purpose:** Enrich a LinkedIn profile with a verified email address.

**Auth:** `Authorization: Bearer <EAZYREACH_API_KEY>`

> **TODO:** Confirm exact base URL and auth scheme with EazyReach support.

### POST /email/find

```bash
curl -X POST https://api.eazyreach.io/v1/email/find \
  -H "Authorization: Bearer $EAZYREACH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "linkedin_url": "https://www.linkedin.com/in/johndoe"
  }'
```

**Response:**
```json
{
  "email": "john.doe@adyen.com",
  "status": "verified",
  "confidence": 0.97,
  "phone": "+31-20-555-0100",
  "location": "Amsterdam, NL",
  "seniority": "director",
  "department": "sales"
}
```

**Status values:** `verified` | `catch_all` | `invalid` | `unknown`

---

## Brevo (Sendinblue)

**Purpose:** Send transactional outreach emails.

**Docs:** https://developers.brevo.com/reference/sendtransacemail

**Auth:** `api-key: <BREVO_API_KEY>`

### POST /smtp/email

```bash
curl -X POST https://api.brevo.com/v3/smtp/email \
  -H "api-key: $BREVO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "sender": {
      "name": "Gurukiran",
      "email": "gurukiran.s@seedlinglabs.com"
    },
    "to": [{ "email": "john@adyen.com", "name": "John Doe" }],
    "subject": "Quick idea for Adyen",
    "textContent": "Hi John,\n\nI came across Adyen..."
  }'
```

**Response:**
```json
{ "messageId": "<abc123@smtp-relay.brevo.com>" }
```
