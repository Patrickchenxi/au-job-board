"""Optional employer sponsorship signals (off unless ``sponsorship.enabled: true``).

A self-contained add-on with three hook points in the main program:

* ``refresh(config)``  -- called at the end of ``fetch`` (network allowed there).
  Re-downloads public reference data when it is older than ``refresh_days``.
* ``run(conn, config)`` -- called after a successful ``analyze``. Offline. Reads
  ``jobs`` / ``decisions`` / ``salary`` and writes ``sponsorship-checks.json``
  next to the database. It never writes scores, decisions, labels or notes.
* ``load_results(config)`` -- read by the panel (see ``sponsorship_panel``).

Reference data lives in ``sponsorship.data_dir`` (default ``data/sponsors``) and is
never committed:

* ``accredited-*.txt`` -- one employer name per line, from the Home Affairs FOI
  release of accredited sponsors. The release is a scanned PDF, so this file is
  produced by OCR (``tools/ocr_sponsor_pdf.ps1`` on Windows; see
  docs/sponsorship.md). Not being on it does not mean an employer cannot sponsor:
  standard business sponsors are not published.
* ``sanctioned.json`` -- the ABF register of sanctioned sponsors, saved as returned.
* ``asx-listed.csv`` -- the ASX list of listed companies.
* ``ato-tax-*.xlsx`` -- ATO corporate tax transparency report (entities with
  total income of $100m or more).

Name matching is deliberately conservative, because brands, franchisees and
unrelated companies share names:

* strict name: legal suffixes removed (Pty Ltd, Limited, Australia, Holdings ...);
  loose name: also generic words (Group, ANZ, International ...).
* accredited list: strict equal = ``exact``; loose equal, or differing only by a
  common company-name tail (Systems, Wholesale ...) = ``fuzzy`` ("possibly").
* sanctions: strict legal-name equal with at least two words = ``confirmed``;
  any other same/similar name, including trading names = ``possible``.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, db_path

SANCTIONS_URL = "https://www.abf.gov.au/_layouts/15/api/Data.aspx/GetSanctionsData"
ASX_URL = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"
ATO_PACKAGE_URL = "https://data.gov.au/data/api/3/action/package_show?id=corporate-transparency"
DEFAULT_REFRESH_DAYS = 30
RESULTS_NAME = "sponsorship-checks.json"

# strict: drop only legal suffixes and the country; the rest of the name must match exactly
_LEGAL = {"pty", "ltd", "limited", "proprietary", "the", "australia", "australian", "aust", "au",
          "holdings", "holding", "services", "corporation", "corp", "company", "inc", "incorporated",
          "plc", "llc", "gmbh", "pte", "and"}
# loose: also drop regions and generic words, to find "possibly the same employer"
_DROP = _LEGAL | {"anz", "apac", "asia", "pacific", "nz", "group", "service", "co", "international",
                  "operations", "trading", "trustee", "trust"}
# The listed name may add one of these to the advertised name ("Example" -> "Example Systems").
_SPONSOR_TAIL = {"systems", "technologies", "technology", "wholesale", "clothing", "supermarkets",
                 "private", "enterprises", "australasia", "victoria", "vic", "lawyers", "motors",
                 "travel", "solutions", "global"}
# The advertised name may add one of these to the listed name ("Example Brands" -> "Example").
_COMPANY_TAIL = {"brands", "new", "zealand"}
# OCR noise in the accredited list: page numbers, headers, watermark fragments
_NOISE = re.compile(r"^\d{1,3}$|freedom of information|released by|department of|home affairs|"
                    r"australian government|list of accredited|^fa \d", re.I)
# Recruiter / anonymous advertisers: the real employer cannot be checked
_AGENCY = re.compile(r"\b(recruit\w*|talent|careers|staffing|personnel|resourcing|search|"
                     r"executive search|placements?|private advertiser)\b", re.I)

_AD_OFFERS = re.compile(
    r"(visa\s+)?sponsorship\s+(is\s+|may\s+be\s+|can\s+be\s+)?(available|offered|provided|considered)|"
    r"(willing|able|happy|open)\s+to\s+sponsor|we\s+(can|will|do)\s+sponsor|"
    r"sponsorship\s+opportunit|482\s+(visa\s+)?sponsor|visa\s+sponsorship\s+for\s+the\s+right", re.I)
_AD_NO = re.compile(
    r"(no|not|unable\s+to|cannot|can't|do\s+not|don't|will\s+not|won't|are\s+not\s+able\s+to)\s+"
    r"(currently\s+)?(offer|provide|support|consider)?\s*(any\s+)?(visa\s+)?sponsor|"
    r"sponsorship\s+(is\s+)?not\s+(available|offered|provided)|without\s+(the\s+need\s+for\s+)?(visa\s+)?sponsorship", re.I)
_AD_PR_ONLY = re.compile(
    r"permanent\s+(right|rights)\s+to\s+work|must\s+be\s+(an?\s+)?(australian\s+)?(citizen|permanent\s+resident)|"
    r"(citizens?|permanent\s+residents?)\s+only|only\s+(australian\s+)?(citizens?|permanent\s+residents?)", re.I)
# "citizen, PR or hold a valid visa / work rights" is open to visa holders
_OPEN_TAIL = re.compile(r"\bor\s+(hold|have|has)\b|\bvisa\b|work(ing)?\s+rights|\bor\s+be\s+eligible", re.I)


# ---- configuration ----

def settings(config: dict) -> dict:
    raw = config.get("sponsorship") if isinstance(config, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    data_dir = Path(raw.get("data_dir") or "data/sponsors")
    return {"enabled": raw.get("enabled") is True,
            "data_dir": data_dir if data_dir.is_absolute() else ROOT / data_dir,
            "refresh_days": int(raw.get("refresh_days") or DEFAULT_REFRESH_DAYS)}


def enabled(config: dict) -> bool:
    return settings(config)["enabled"]


# ---- names ----

def _norm_tokens(name: str, drop: set[str] = _DROP) -> list[str]:
    name = (name or "").split("|")[0]
    name = re.sub(r"\(.*?\)", " ", name).lower().replace("&", " and ")
    tokens = re.findall(r"[a-z0-9#]+", name)
    return [t for t in tokens if t not in drop]


def _key(name: str) -> str:
    return " ".join(_norm_tokens(name))


def _strict(name: str) -> str:
    return " ".join(_norm_tokens(name, _LEGAL))


class NameIndex:
    """Matcher over a list of employer names: ``match(company) -> (exact|fuzzy|None, listed name)``."""

    def __init__(self, names: list[str]):
        self.strict = {_strict(n): n for n in names}
        self.loose: dict[str, str] = {}
        self.by_first: dict[str, list[tuple[list[str], str]]] = {}
        for original in names:
            tokens = _norm_tokens(original)
            if not tokens:          # nothing left after removing suffixes
                continue
            self.loose.setdefault(" ".join(tokens), original)
            self.by_first.setdefault(tokens[0], []).append((tokens, original))

    def match(self, company: str) -> tuple[str | None, str | None]:
        tokens = _norm_tokens(company)
        if not tokens:
            return None, None
        if (hit := self.strict.get(_strict(company))):
            return "exact", hit
        if (hit := self.loose.get(" ".join(tokens))):
            return "fuzzy", hit
        for listed, original in self.by_first.get(tokens[0], []):
            if len(listed) > len(tokens) and listed[:len(tokens)] == tokens and set(listed[len(tokens):]) <= _SPONSOR_TAIL:
                return "fuzzy", original
            if len(tokens) > len(listed) and tokens[:len(listed)] == listed and set(tokens[len(listed):]) <= _COMPANY_TAIL:
                return "fuzzy", original
        return None, None


class Sanctions:
    """strict legal name (2+ words) = confirmed; same/similar name or trading name = possible."""

    def __init__(self, rows: list[dict]):
        self.confirmed: dict[str, dict] = {}
        self.possible: dict[str, dict] = {}
        for r in rows:
            entry = {"name": (r.get("sponsorname") or "").strip(), "trading": (r.get("tradingname") or "").strip(),
                     "abn": r.get("abn"), "sanction": r.get("sanctionimposed"),
                     "date": r.get("sanctionimposeddatetext"), "end": r.get("sanctionenddate"),
                     "state": r.get("state")}
            legal = _strict(entry["name"])
            if len(legal.split()) >= 2:
                self.confirmed.setdefault(legal, entry)
            for name in (entry["name"], entry["trading"]):
                if (key := _key(name)):
                    self.possible.setdefault(key, entry)

    def match(self, company: str) -> tuple[str | None, dict | None]:
        if (hit := self.confirmed.get(_strict(company))):
            return "confirmed", hit
        if (key := _key(company)) and (hit := self.possible.get(key)):
            return "possible", hit
        return None, None


# ---- reference data ----

def load_accredited(data_dir: Path) -> list[str]:
    names: dict[str, str] = {}
    for path in sorted(data_dir.glob("accredited-*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if len(re.findall(r"[A-Za-z]", line)) < 3 or _NOISE.search(line):
                continue
            names.setdefault(_strict(line), line)
    return [n for n in names.values() if _key(n)]


def load_sanctions(data_dir: Path) -> Sanctions:
    path = data_dir / "sanctioned.json"
    rows = (json.loads(path.read_text(encoding="utf-8")).get("d", {}).get("data") or []) if path.exists() else []
    return Sanctions(rows)


def _stale(path: Path, days: int) -> bool:
    return not path.exists() or (datetime.now().timestamp() - path.stat().st_mtime) >= days * 86400


_USER_AGENT = {"User-Agent": "au-job-board (sponsorship reference data)"}


def _download(request, target: Path, check=None) -> None:
    if isinstance(request, str):
        request = urllib.request.Request(request, headers=_USER_AGENT)
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    if check is not None:
        check(body)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(target)


def _check_sanctions(body: bytes) -> None:
    if not json.loads(body).get("d", {}).get("success"):
        raise ValueError("sanctions endpoint returned no data")


def _latest_ato_url() -> tuple[str, str] | None:
    with urllib.request.urlopen(ATO_PACKAGE_URL, timeout=60) as response:
        package = json.loads(response.read())["result"]
    reports = []
    for resource in package.get("resources") or []:
        year = re.match(r"(\d{4}-\d{2}) Report of Entity Tax Information", resource.get("name") or "")
        if year and str(resource.get("url") or "").lower().endswith(".xlsx"):
            reports.append((year.group(1), resource["url"]))
    return max(reports) if reports else None


def refresh(config: dict) -> list[str]:
    """Fetch-stage only. Re-download stale reference data; failures keep the old files.

    Returns the names of the files that were updated. The accredited list is not
    downloaded here: it needs OCR (see docs/sponsorship.md).
    """
    cfg = settings(config)
    if not cfg["enabled"]:
        return []
    data_dir, days, updated = cfg["data_dir"], cfg["refresh_days"], []
    jobs = [
        ("sanctioned.json", lambda: _download(urllib.request.Request(
            SANCTIONS_URL, data=b"{}", method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"}),
            data_dir / "sanctioned.json", _check_sanctions)),
        ("asx-listed.csv", lambda: _download(ASX_URL, data_dir / "asx-listed.csv")),
    ]
    for name, action in jobs:
        if not _stale(data_dir / name, days):
            continue
        try:
            action()
            updated.append(name)
        except (OSError, ValueError) as exc:
            print(f"[sponsorship] {name} refresh failed, keeping the old file ({type(exc).__name__})")
    existing = sorted(data_dir.glob("ato-tax-*.xlsx"))
    if not existing or _stale(existing[-1], days):
        try:
            latest = _latest_ato_url()
            if latest and not (data_dir / f"ato-tax-{latest[0]}.xlsx").exists():
                _download(latest[1], data_dir / f"ato-tax-{latest[0]}.xlsx")
                updated.append(f"ato-tax-{latest[0]}.xlsx")
        except (OSError, ValueError, KeyError) as exc:
            print(f"[sponsorship] ATO report refresh failed, keeping the old file ({type(exc).__name__})")
    return updated


# ---- the ad text ----

def _snippet(text: str, m: re.Match, width: int = 90) -> str:
    start, end = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def scan_ad(text: str) -> tuple[str | None, str | None]:
    """What the ad says about sponsorship: pr_only / no / offers, with the quoted text."""
    text = re.sub(r"\s+", " ", text or "")
    for kind, pattern in (("pr_only", _AD_PR_ONLY), ("no", _AD_NO), ("offers", _AD_OFFERS)):
        for m in pattern.finditer(text):
            if kind == "pr_only" and _OPEN_TAIL.search(text[m.end():m.end() + 80]):
                continue
            return kind, _snippet(text, m)
    return None, None


# ---- the check ----

def check_all(conn, data_dir: Path) -> dict[str, dict]:
    from . import sponsorship_fit

    accredited = NameIndex(load_accredited(data_dir))
    sanctions = load_sanctions(data_dir)
    companies = sponsorship_fit.Companies(data_dir, NameIndex)
    results: dict[str, dict] = {}
    cache: dict[str, tuple] = {}
    for uid, company, description, teaser, title, annual_min, annual_max, excluded in conn.execute(
            "SELECT j.uid, j.company, j.description, j.teaser, j.title, sal.annual_min, sal.annual_max, "
            "COALESCE(d.is_excluded, 0) FROM jobs j "
            "LEFT JOIN salary sal ON sal.uid = j.uid LEFT JOIN decisions d ON d.uid = j.uid"):
        company = company or ""
        if company not in cache:
            cache[company] = (accredited.match(company), sanctions.match(company),
                              bool(_AGENCY.search(company)), companies.lookup(company))
        (acc, acc_name), (sanction_level, sanction), agency, size = cache[company]
        ad, ad_text = scan_ad(description or teaser or "")
        check = {"acc": acc, "acc_name": acc_name, "sanction": sanction,
                 "sanction_level": sanction_level, "agency": agency, "ad": ad, "ad_text": ad_text}
        if not excluded:
            job = {"title": title, "company": company, "description": description or teaser or "",
                   "annual_min": annual_min, "annual_max": annual_max}
            check["fit"] = sponsorship_fit.assess(job, check, size)
        if acc or sanction or agency or ad or check.get("fit"):
            results[uid] = check
    return results


def results_path(config: dict) -> Path:
    return db_path(config).resolve().parent / RESULTS_NAME


def run(conn, config: dict) -> dict | None:
    """After a successful analyze. Offline; writes only the side file."""
    cfg = settings(config)
    if not cfg["enabled"]:
        return None
    results = check_all(conn, cfg["data_dir"])
    payload = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "accredited_entries": len(load_accredited(cfg["data_dir"])), "results": results}
    path = results_path(config)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    ratings = [r["fit"]["rating"] for r in results.values() if r.get("fit")]
    print(f"[sponsorship] accredited {sum(1 for r in results.values() if r.get('acc'))} | "
          f"sanctions {sum(1 for r in results.values() if r.get('sanction'))} | "
          f"ad mentions {sum(1 for r in results.values() if r.get('ad'))} | "
          + " | ".join(f"{k} {ratings.count(k)}" for k in ("high", "medium", "low", "no")))
    return payload


_CACHE: dict[str, tuple[float, dict]] = {}


def load_results(config: dict) -> dict[str, dict]:
    """For the panel: cached by file mtime; empty when disabled or not yet run."""
    if not enabled(config):
        return {}
    path = results_path(config)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        results = json.loads(path.read_text(encoding="utf-8")).get("results") or {}
    except (OSError, ValueError):
        results = {}
    _CACHE[str(path)] = (mtime, results)
    return results
