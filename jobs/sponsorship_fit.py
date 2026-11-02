"""A rough "is it worth asking this employer for sponsorship?" likelihood (0-100).

Part of the optional sponsorship add-on (see ``jobs/sponsorship.py``). It is a
pointer assembled from public data, not a migration assessment, and it says
nothing about the user. Three groups of signals:

1. Can and would the employer sponsor: the accredited sponsor list, ASX listing,
   the ATO corporate tax transparency report (entities with total income of
   $100m or more). Almost any lawfully operating Australian business can apply to
   become a standard business sponsor, so size is only a hint, not a gate.
2. Can this role be sponsored: job title -> occupation (``OCCUPATIONS``; each code
   was checked against the Home Affairs Core Skills Occupation List PDF) and
   whether the parsed salary reaches the Core Skills Income Threshold.
3. The ad text: "no sponsorship" or "PR / citizens only" sets the likelihood to 0.

Every reason carries its points (``POINTS``) so the panel can show the sum.
Core Skills sponsorship also needs one year of relevant experience; that is
shown as a reminder only.
"""
from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path

# Core Skills Income Threshold from 2026-07-01 (most sources: $79,423). Indexed each 1 July.
CSIT = 79_423
CSIT_AS_OF = "2026-07-01"

# Tech-product context. Ads mention data / digital / technology in passing, so the
# body only counts strong words, or at least four different weak ones; any of them
# in the title or company name counts.
_TECH_STRONG = re.compile(r"\b(saas|software|cloud|ict|cyber\w*|erp|crm|it solutions|managed (it )?services|"
                          r"tech(nology)? company|b2b tech|it hardware)\b", re.I)
_TECH_WEAK = re.compile(r"\b(technology|tech|digital|data|ai|automation|analytics|platform|fintech|payments?|"
                        r"computer\w*|telco|telecom\w*)\b", re.I)
_IT = re.compile(r"\bIT\b")          # case-sensitive: "It" at a sentence start is not IT
_MEDICAL = re.compile(r"\b(medical|pharma\w*|medtech|devices?|clinical|diagnostic\w*|healthcare|hospital|surgical)\b", re.I)
_INDUSTRIAL = re.compile(r"\b(industrial|equipment|machinery|building (products|materials)|construction|"
                         r"manufactur\w*|chemical\w*|fasteners?|engineering|hvac|electrical|packaging|ingredients)\b", re.I)

_SALES = re.compile(r"\b(sdr|bdr|xdr|sales|business development rep\w*|inside sales|appointment setter|"
                    r"account executive|outbound|territory|area manager)\b", re.I)
_PRESALES = re.compile(r"\b(pre-?sales|sales engineer|solutions? (consultant|engineer|architect|specialist))\b", re.I)
_ACCOUNT_MGR = re.compile(r"\b(account (manager|director|lead)|key account|client executive|client partner)\b", re.I)
_BD = re.compile(r"\bbusiness develop\w*\b", re.I)

# (title pattern, required context, code, occupation, confidence); first match wins.
# Context None = any; "tech"/"medical"/"industrial" = title + company + body must show it.
OCCUPATIONS = [
    (_PRESALES, None, "225499", "Technical Sales Representatives nec", "likely"),
    (_SALES, "tech", "225213", "ICT Sales Representative", "likely"),
    (_ACCOUNT_MGR, "tech", "225211", "ICT Account Manager", "likely"),
    (_BD, "tech", "225212", "ICT Business Development Manager", "likely"),
    (_SALES, "medical", "225412", "Sales Representative (Medical and Pharmaceutical Products)", "likely"),
    (_SALES, "industrial", "225411", "Sales Representative (Industrial Products)", "likely"),
    (_ACCOUNT_MGR, "medical", "225412", "Sales Representative (Medical and Pharmaceutical Products)", "possible"),
    (_ACCOUNT_MGR, "industrial", "225411", "Sales Representative (Industrial Products)", "possible"),
    (re.compile(r"\b(business|systems|it|ict|technical|solutions?) analyst", re.I), "tech",
     "261111", "ICT Business Analyst", "likely"),
    (re.compile(r"\bbusiness analyst", re.I), None, "224712", "Organisation and Methods Analyst", "possible"),
    (re.compile(r"\bdata scien", re.I), None, "224115", "Data Scientist", "likely"),
    (re.compile(r"\b(data|insights?|reporting|bi|analytics) (and \w+ )?analyst", re.I), None,
     "224114", "Data Analyst", "likely"),
    (re.compile(r"\b(supply chain|demand|inventory|planning) (analyst|planner)|\b(demand|junior) planner", re.I), None,
     "224714", "Supply Chain Analyst", "likely"),
    (re.compile(r"\brecruit\w* consultant", re.I), None, "223112", "Recruitment Consultant", "likely"),
    (re.compile(r"\b(management|strategy|strategic|business|transformation|change|digital strategy) consult", re.I), None,
     "224713", "Management Consultant", "likely"),
    (re.compile(r"\bmarketing (specialist|executive|coordinator|manager|consultant)", re.I), None,
     "225113", "Marketing Specialist", "possible"),
    (re.compile(r"\b(pricing|commercial|operations|process improvement|organi[sz]ation and methods|"
                r"graduate|junior|associate) (\w+ )?analyst", re.I), None,
     "224712", "Organisation and Methods Analyst", "possible"),
    (re.compile(r"\b(junior |graduate |associate )?consultant\b", re.I), None, "224713", "Management Consultant", "possible"),
]
# Sales outside the Core Skills list: retail, store, door-to-door, broking, call centres
_NOT_LISTED = re.compile(r"\b(retail|store|shop|sales (assistant|associate)|promoter|promotions|door|call centre|"
                         r"telesales|broker|real estate|travel (sales|consultant)|customer service)\b", re.I)


def _is_tech(title: str, company: str, description: str) -> bool:
    head = f"{title} {company}"
    if _TECH_STRONG.search(head) or _TECH_WEAK.search(head) or _IT.search(head):
        return True
    if _TECH_STRONG.search(description):
        return True
    weak = {m.lower() for m in _TECH_WEAK.findall(description)} | ({"IT"} if _IT.search(description) else set())
    return len(weak) >= 4


def map_occupation(title: str, company: str, description: str) -> dict | None:
    title = title or ""
    description = (description or "")[:4000]
    context = f"{title} {company or ''} {description}"
    if _NOT_LISTED.search(title):
        return {"code": None, "name": None, "confidence": "not_listed"}
    tech = _is_tech(title, company or "", description)
    for pattern, need, code, name, confidence in OCCUPATIONS:
        if not pattern.search(title):
            continue
        if need == "tech" and not tech:
            continue
        if need == "medical" and not _MEDICAL.search(context):
            continue
        if need == "industrial" and not _INDUSTRIAL.search(context):
            continue
        return {"code": code, "name": name, "confidence": confidence}
    if _SALES.search(title) or _ACCOUNT_MGR.search(title) or _BD.search(title):
        if len(description) < 300:
            return None          # no body text: cannot tell what is being sold
        return {"code": None, "name": None, "confidence": "generic_sales"}
    return None


# ---- company size data ----

def load_asx(data_dir: Path) -> list[str]:
    path = data_dir / "asx-listed.csv"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("Company name")), None)
    if start is None:
        return []
    return [row["Company name"] for row in csv.DictReader(lines[start:]) if row.get("Company name")]


def _xlsx_rows(path: Path, sheet: int):
    """Read an .xlsx sheet with the standard library only: yields lists of cell text."""
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8")
            strings = [re.sub(r"<[^>]+>", "", s) for s in re.findall(r"<si>(.*?)</si>", xml, re.S)]
        xml = z.read(f"xl/worksheets/sheet{sheet}.xml").decode("utf-8")
    for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
        cells = []
        for attrs, body in re.findall(r"<c([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
            value = re.search(r"<v>(.*?)</v>", body or "")
            text = value.group(1) if value else re.sub(r"<[^>]+>", "", body or "")
            if 't="s"' in attrs and value:
                text = strings[int(text)]
            cells.append(text.replace("&amp;", "&"))
        yield cells


def load_ato(data_dir: Path) -> tuple[dict[str, float], str | None]:
    """Company name -> total income from the newest ato-tax-*.xlsx (sheet 2)."""
    files = sorted(data_dir.glob("ato-tax-*.xlsx"))
    if not files:
        return {}, None
    income: dict[str, float] = {}
    header = None
    for cells in _xlsx_rows(files[-1], 2):
        if header is None:
            if "Name" in cells and any("Total income" in c for c in cells):
                header = cells
            continue
        record = dict(zip(header, cells))
        name = record.get("Name")
        total = next((v for k, v in record.items() if "Total income" in k), None)
        try:
            income[name] = max(income.get(name, 0.0), float(total))
        except (TypeError, ValueError):
            continue
    year = re.search(r"\d{4}-\d{2}", files[-1].name)
    return income, (year.group(0) if year else None)


class Companies:
    """ASX and ATO lookups using the same conservative matcher as the accredited list."""

    def __init__(self, data_dir: Path, matcher_cls):
        self.asx = matcher_cls(load_asx(data_dir))
        self.income, self.ato_year = load_ato(data_dir)
        self.ato = matcher_cls(list(self.income))

    def lookup(self, company: str) -> dict:
        asx_level, asx_name = self.asx.match(company)
        ato_level, ato_name = self.ato.match(company)
        return {"asx": asx_level, "asx_name": asx_name, "ato": ato_level, "ato_name": ato_name,
                "ato_income": self.income.get(ato_name) if ato_name else None, "ato_year": self.ato_year}


# ---- likelihood ----

LIKELIHOOD_BASE = 20          # any lawfully operating Australian business can apply to sponsor
POINTS = {
    "fit.r_accredited": 35, "fit.r_accredited_fuzzy": 15, "fit.r_ad_offers": 25,
    "fit.r_asx_exact": 10, "fit.r_asx_fuzzy": 5, "fit.r_ato_exact": 10, "fit.r_ato_fuzzy": 5,
    "fit.r_occ_likely": 15, "fit.r_occ_possible": 5, "fit.r_occ_unknown": 0,
    "fit.r_occ_generic_sales": -15, "fit.r_occ_not_listed": -25,
    "fit.r_salary_ok": 5, "fit.r_salary_low": -10, "fit.r_salary_unknown": 0,
    "fit.r_agency": -10, "fit.r_sanction_possible": -5, "fit.r_company_unknown": 0,
}
SANCTION_CAP = 5              # a confirmed sanction caps the likelihood


def _rating(likelihood: int) -> str:
    if likelihood <= 0:
        return "no"
    if likelihood >= 70:
        return "high"
    if likelihood >= 40:
        return "medium"
    return "low"


def assess(job: dict, check: dict, company: dict) -> dict:
    """job: title/company/description/annual_min/annual_max; check: from sponsorship.check_all.

    certain    -- on the accredited list (exact) or the ad says it sponsors
    likelihood -- LIKELIHOOD_BASE plus POINTS, clamped to 1..100 (0 when the ad rules it out)
    rating     -- high >= 70 / medium >= 40 / low > 0 / no = 0
    reasons    -- [(i18n key, params, points or None)]
    """
    reasons: list[tuple[str, dict, int | None]] = []
    occupation = map_occupation(job.get("title"), job.get("company"), job.get("description"))

    def add(key: str, params: dict | None = None, points_key: str | None = None):
        reasons.append((key, params or {}, POINTS.get(points_key or key)))

    certain = check.get("acc") == "exact" or check.get("ad") == "offers"
    if check.get("ad") in ("no", "pr_only"):
        return {"rating": "no", "likelihood": 0, "certain": certain, "occupation": occupation,
                "reasons": [("fit.r_ad_" + check["ad"], {}, None)]}

    # the employer
    if check.get("acc") == "exact":
        add("fit.r_accredited")
    elif check.get("acc") == "fuzzy":
        add("fit.r_accredited_fuzzy", {"name": check.get("acc_name") or ""})
    if check.get("ad") == "offers":
        add("fit.r_ad_offers")
    if company.get("asx"):
        add("fit.r_asx", {"name": company.get("asx_name") or ""}, f"fit.r_asx_{company['asx']}")
    if company.get("ato") and company.get("ato_income"):
        add("fit.r_ato", {"income": f"{company['ato_income'] / 1e6:,.0f}", "year": company.get("ato_year") or "",
                          "name": company.get("ato_name") or ""}, f"fit.r_ato_{company['ato']}")
    if check.get("agency"):
        add("fit.r_agency")
    elif not (check.get("acc") or company.get("asx") or company.get("ato")):
        add("fit.r_company_unknown")
    if check.get("sanction") and check.get("sanction_level") != "confirmed":
        add("fit.r_sanction_possible")

    # the role
    if occupation is None:
        add("fit.r_occ_unknown")
    elif occupation["confidence"] in ("not_listed", "generic_sales"):
        add(f"fit.r_occ_{occupation['confidence']}")
    else:
        add(f"fit.r_occ_{occupation['confidence']}", {"code": occupation["code"], "name": occupation["name"]})
    top = job.get("annual_max") or job.get("annual_min")
    if top:
        add("fit.r_salary_ok" if top >= CSIT else "fit.r_salary_low", {"salary": f"{top:,.0f}", "csit": f"{CSIT:,}"})
    else:
        add("fit.r_salary_unknown", {"csit": f"{CSIT:,}"})

    likelihood = max(1, min(100, LIKELIHOOD_BASE + sum(p for _, _, p in reasons if p)))
    if check.get("sanction") and check.get("sanction_level") == "confirmed":
        reasons.insert(0, ("fit.r_sanction", {"date": check["sanction"].get("date") or ""}, None))
        likelihood = min(likelihood, SANCTION_CAP)
        certain = False
    reasons.append(("fit.r_experience", {}, None))
    return {"rating": _rating(likelihood), "likelihood": likelihood, "certain": certain,
            "occupation": occupation, "reasons": reasons}
