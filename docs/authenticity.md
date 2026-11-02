# Job-ad scam risk (optional)

This add-on is **off by default**. When it is off nothing on this page runs, and
the panel, scores and reports are unchanged.

Job and employment scams grew fastest of all scam types reported to Scamwatch in
2023. Scammers also post on trusted job boards. The add-on looks for the warning
signs Scamwatch and the ACCC describe, and gives each ad a 0–100 **scam risk** with
the quoted evidence. It is a prompt to take a closer look, **not a verdict**.
Most scams only show themselves after you apply, so a low score does not mean an
ad is safe.

## What it shows

- **Cards:** a badge only when the risk is medium (25–49) or high (50+). Low-risk
  ads look exactly as before.
- **Job detail:** one row, "Is this ad genuine?", with the level and percentage.
  Hovering (or focusing) it opens the evidence: every sign with its points and
  the sentence it came from, plus one-click ways to check the employer yourself:
  a web search for the employer's own site, ABN Lookup, and Scamwatch's job-scam
  page.

The add-on writes only `authenticity-checks.json` next to the database. It never
writes scores, decisions, labels or notes.

## Signals

The risk starts at 5%, then each signal adds or removes points:

| Signal (Scamwatch / ACCC warning sign) | Points |
|---|---|
| You are asked to pay: a fee, starter kit, training, visa, bond… | +40 |
| Topping up an account or wallet, or being paid in crypto / USDT | +40 |
| Receiving or forwarding money or parcels for someone else | +40 |
| Paid "tasks": liking, rating or "optimising" products or apps | +35 |
| Contact through WhatsApp / Telegram / Signal / WeChat | +30 |
| ID documents or bank details requested in the ad | +20 |
| Hiring without an interview | +15 |
| High pay for little effort ("earn $300 a day from home") | +15 |
| "Be your own boss" / recruit-others wording | +10 |
| Pressure to act fast | +5 |
| Email at a free provider (Gmail, Outlook, Yahoo…) | +15 |
| Email domain does not match the employer's name | +10 |
| A quoted email or web domain does not exist (DNS lookup) | +20 |
| Employer name hidden ("Private Advertiser", "Confidential") | +10 |
| Pay of $150k+ for a role described as junior or entry level | +15 |
| The same ad text under 4+ different employer names | +15 |
| Very short ad (under 300 characters) | +5 |
| Email domain matches the employer's name | −5 |
| Employer on the accredited sponsor list (if the sponsorship add-on has run) | −15 |
| Employer ASX-listed or in the ATO large-company report (same) | −15 |

The patterns are deliberately narrow, because real ads use the same words
innocently. A payment, crypto, money-transfer, messaging-app or ID sign does not
count inside a sentence that warns against scams (for example "we will never ask
you to pay a fee or contact you on WhatsApp"). "Paid training", a crypto company
describing its products, or a product that "sends messages via WhatsApp" are not
signs. Only email domains are compared with the employer's name, because links in
ads often point to press, partners or a parent company.

## Limits

- It reads the ad, not the conversation. Requests for money or ID usually come
  later, by message or email.
- It does not visit the employer's careers page. The links in the detail make
  that a few clicks.
- Name and domain matching is heuristic. A legitimate employer can use an
  unrelated domain, and a scam can use a convincing one.
- No platform verification flag is available from the sources, so "posted on a
  big job board" counts for nothing. Scamwatch warns that scammers post there too.

## Turning it on

```yaml
authenticity:
  enabled: true
  check_domains: true          # DNS-check quoted domains during fetch
  data_dir: data/authenticity  # cache of domain lookups
  refresh_days: 30
```

Only `fetch` (and therefore `run` and the panel's update) uses the network, and
only for DNS lookups of domains quoted in ads: at most 300 per fetch, 5-second
timeout, cached for `refresh_days`. `analyze` is offline.

## Sources

- Scamwatch, [Jobs and employment scams](https://www.scamwatch.gov.au/types-of-scams/jobs-and-employment-scams)
- Scamwatch, [Scam alert: job scams on the rise](https://www.scamwatch.gov.au/about-us/news-and-alerts/scam-alert-job-scams-on-the-rise)
- ACCC, [New year, new job? Beware of scammers](https://www.accc.gov.au/media-release/new-year-new-job-beware-of-scammers)
