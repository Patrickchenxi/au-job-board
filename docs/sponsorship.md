# Employer sponsorship signals (optional)

This add-on is **off by default**. When it is off, nothing on this page runs and
the panel, scores and reports are unchanged.

People on a temporary visa often shortlist jobs and then ask two questions: is
this employer able to sponsor, and could this role be sponsored at all? The
add-on gathers public data to answer the first question and gives a rough
pointer for the second. It is **not migration advice**, and it does not judge the
user.

## What it shows

After `analyze`, cards that have results gain up to four tags, and the job detail
gains one compact block with three rows. Each row shows only its conclusion;
hovering (or focusing) it opens the evidence behind it:

1. **Can this employer definitely sponsor?** "Confirmed" only when the employer
   is on the Home Affairs accredited sponsor list (exact name match) or the ad
   says it sponsors. A confirmed ABF sanction overrides this.
2. **Sponsorship likelihood**: a 0–100% meter. It starts at 20%, because almost
   any lawfully operating Australian business can apply to become a standard
   business sponsor. Each signal then adds or removes points, and the row's
   popup lists every one:

   | Signal | Points |
   |---|---|
   | On the accredited list (exact / similar name) | +35 / +15 |
   | The ad says it sponsors | +25 |
   | ASX listed (exact / similar name) | +10 / +5 |
   | In the ATO tax transparency report (exact / similar name) | +10 / +5 |
   | Title likely / possibly maps to a Core Skills occupation | +15 / +5 |
   | General sales / retail-type role with no matching occupation | −15 / −25 |
   | Parsed salary at or above / below the Core Skills Income Threshold | +5 / −10 |
   | Recruiter or anonymous advertiser | −10 |
   | Same or similar name on the sanctions register | −5 |

   An ad that says "no sponsorship" or "PR / citizens only" sets the likelihood
   to 0%. A confirmed sanction caps it at 5%. Excluded jobs are not rated. The
   points live in `jobs/sponsorship_fit.py` (`POINTS`).
3. **What the ad says**: "PR / citizens only", "no sponsorship" or "mentions
   sponsorship", with the quoted sentence. A sentence that continues with
   "or hold a valid visa" or "work rights" is not treated as PR-only.

The add-on writes only `sponsorship-checks.json` next to the database. It never
writes scores, decisions, labels or notes.

## Limits

- Matching is by company name. Advertised names and legal names often differ,
  brands have franchisees, and unrelated companies share names. Exact legal-name
  matches are "confirmed"; everything else is shown as "possibly".
- Not being on the accredited list does not mean an employer cannot sponsor:
  standard business sponsors are not published. The accredited list is a
  point-in-time FOI release.
- The occupation is guessed from the job title and ad text, using a short table
  of codes checked against the official Core Skills Occupation List. Ads with no
  body text cannot be mapped.
- The Core Skills Income Threshold is a constant (`CSIT` in
  `jobs/sponsorship_fit.py`) that needs updating every 1 July.
- Core Skills sponsorship also needs one year of relevant experience. The detail
  shows this as a reminder only.

## Turning it on

```yaml
sponsorship:
  enabled: true
  data_dir: data/sponsors    # relative to the project root, or absolute
  refresh_days: 30           # re-download reference data older than this
```

## Reference data

Everything lives in `data_dir`, which is under `data/` by default and is never
committed.

| File | Source | How it gets there |
|---|---|---|
| `sanctioned.json` | ABF register of sanctioned sponsors (the JSON behind the register page) | downloaded during `fetch` |
| `asx-listed.csv` | ASX list of listed companies | downloaded during `fetch` |
| `ato-tax-<year>.xlsx` | ATO corporate tax transparency report on data.gov.au (newest year) | downloaded during `fetch` |
| `accredited-*.txt` | Home Affairs FOI release of accredited sponsors, one name per line | manual: see below |

Only `fetch` (and therefore `run` and the panel's update) uses the network.
`analyze` stays offline and works with whatever files are present. Missing files
simply mean fewer signals.

### The accredited sponsor list

Home Affairs publishes this list on its FOI disclosure log as a scanned PDF (for
example FA 25/01/01229, "List of accredited Temporary Resident (Skilled
Employment) sponsors"), so it has to be turned into text first:

- **Windows:** `tools/ocr_sponsor_pdf.ps1` uses the built-in Windows OCR:

  ```powershell
  & .\tools\ocr_sponsor_pdf.ps1 -PdfPath data\sponsors\accredited-2025-01.pdf `
      -OutPath data\sponsors\accredited-2025-01.txt
  ```

- **Other platforms:** any OCR tool that writes one name per line works. Page
  numbers, headers and watermark fragments are filtered out when the file is
  loaded.

Several `accredited-*.txt` files are merged.
