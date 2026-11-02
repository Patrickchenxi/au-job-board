"""Optional job-ad scam-risk check (off unless ``authenticity.enabled: true``).

A self-contained add-on, like the other optional checks:

* ``refresh(conn, config)`` -- end of ``fetch`` (network allowed): looks up whether
  the email / website domains quoted in recent ads exist (DNS only), cached in
  ``<data_dir>/domains.json``.
* ``run(conn, config)`` -- after a successful ``analyze``. Offline. Writes only
  ``authenticity-checks.json`` next to the database; never scores, decisions,
  labels or notes.
* ``load_results(config)`` -- read by ``authenticity_panel``.

The warning signs follow public guidance from Scamwatch / the ACCC on job and
employment scams: upfront payments or "top-ups" (often in crypto), moving the
conversation to WhatsApp / Telegram / Signal, high pay for little effort,
hiring without an interview, moving money or parcels for someone else, and early
requests for identity or bank details. Each sign adds points to a 0-100 risk;
public signs of an established employer take some away. The result is a pointer
for a closer look, never a verdict: the panel says so and links to the official
ways to check (the employer's own site found independently, ABN Lookup,
Scamwatch).

What it cannot do: visit the employer's careers page, verify a recruiter's
identity, or see messages sent after applying. Most scams start after contact,
so a low score does not mean an ad is safe.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, db_path

RESULTS_NAME = "authenticity-checks.json"
DEFAULT_REFRESH_DAYS = 30
MAX_LOOKUPS_PER_FETCH = 300
BASE = 5

# (key, points, pattern). Matched on the ad text. The narrow patterns below were tuned
# against real ads, where these words mostly appear innocently (paid training, a
# crypto employer, a product that integrates WhatsApp).
SIGNS: list[tuple[str, int, re.Pattern]] = [
    ("upfront_payment", 40, re.compile(
        r"\byou (will )?(need to|must|have to|are required to|'ll need to) (pay|purchase|buy|deposit)\b|"
        r"\b(pay|purchase|buy) (a|an|the|your own)? ?(\w+ )?(registration|training|application|joining|"
        r"starter|onboarding|placement|visa|bond) (fee|kit|pack)\b|"
        r"\b(registration|training|application|joining|starter|onboarding|refundable) fee\b|"
        r"\bstarter kit\b", re.I)),
    ("crypto_topup", 40, re.compile(
        r"\b(top[- ]?up|recharge|deposit (into|to))\b[^.]{0,30}\b(account|wallet|balance)\b|"
        r"\b(paid|payment|salary|commission|wages?) (is |are )?(paid )?in (crypto(currency)?|usdt|bitcoin|tether)\b|"
        r"\busdt\b", re.I)),
    ("money_mule", 40, re.compile(
        r"\b(receive|process|transfer|forward)\w*\b[^.]{0,30}\b(payments?|funds|money)\b[^.]{0,30}\b(on behalf|for (our|the) (company|clients?))|"
        r"\b(reshipp\w*|parcel forward\w*|package (receiver|handler|inspector)|payment (processing )?agent|"
        r"money transfer agent|financial agent)\b", re.I)),
    ("task_scam", 35, re.compile(
        r"\b(like|rate|review|optimi[sz]e|boost)\b[^.]{0,30}\b(products?|apps?|videos?|posts?|hotels?|ratings?)\b[^.]{0,40}\b(earn|commission|per task)|"
        r"\b(complete|simple|daily) (\d+ )?tasks?\b[^.]{0,40}\b(earn|commission|paid)|data optimi[sz]ation", re.I)),
    ("messaging_app", 30, re.compile(
        r"\b(contact|message|text|msg|reach|add|chat with|apply|send (us |me )?(your )?(cv|resume))\b[^.]{0,20}"
        r"\b(on|via|through|at|using)\s+(whats ?app|telegram|signal|wechat|viber)\b|"
        r"\b(whats ?app|telegram|wechat|viber)\s*(me|us|only)\b|"
        r"\b(whats ?app|telegram|wechat|viber)\s*[:\-]?\s*\+?\d[\d\s]{6,}", re.I)),
    ("id_early", 20, re.compile(
        r"\b(send|provide|submit|attach)\b[^.]{0,40}\b(passport|driver'?s licen[cs]e|bank (account )?details|"
        r"tax file number|tfn|medicare card|credit card)\b", re.I)),
    ("no_interview", 15, re.compile(
        r"\bno interviews?\b|\bwithout (an )?interview\b|\bhired on the spot\b|\binstant (hire|approval|start)\b", re.I)),
    ("easy_money", 15, re.compile(
        r"\b(earn|make)\b[^.]{0,20}\$\s?\d[\d,]*\s*(\+\s*)?(per|a|/)\s*(day|hour|hr|week)\b[^.]{0,60}\b(from home|no experience|easy|flexible)|"
        r"\beasy (money|cash|income)\b|\b(make|earn) money (fast|from home|online)\b", re.I)),
    ("mlm", 10, re.compile(
        r"\b(be your own boss|financial freedom|unlimited (earning|income) potential|passive income|"
        r"recruit (others|your friends)|build your (own )?team)\b", re.I)),
    ("urgency", 5, re.compile(
        r"\b(limited (spots|positions|places)|spots (are )?filling (up )?fast|act now|only \d+ (spots|positions) left)\b", re.I)),
]
_NEGATION = re.compile(r"\b(never|no|not|without|free of|don'?t|do not|won'?t|will not)\b[^.]{0,25}$", re.I)
# Employers' own anti-scam notices ("we will never ask you to pay a fee", "requests via
# WhatsApp should be treated as fraudulent") use the same words; inside such a
# sentence the payment / contact / ID signs do not count.
_WARNING_SENTENCE = re.compile(r"\b(never|not|fraud\w*|scam\w*|purport\w*|unofficial|beware|phishing|"
                               r"impersonat\w*|genuine|legitimate|suspicious)\b", re.I)
_SENTENCE_GUARDED = {"upfront_payment", "crypto_topup", "money_mule", "messaging_app", "id_early"}

_EMAIL = re.compile(r"\b[\w.+-]+@([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", re.I)
_URL = re.compile(r"\b(?:https?://|www\.)([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)
_FREEMAIL = {"gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com", "yahoo.com",
             "yahoo.com.au", "icloud.com", "me.com", "qq.com", "163.com", "proton.me", "protonmail.com",
             "aol.com", "gmx.com", "bigpond.com", "optusnet.com.au"}
# Job boards, applicant-tracking systems and common platforms: not the employer's own domain.
_PLATFORMS = re.compile(r"(?:^|\.)(seek|linkedin|indeed|jora|workforceaustralia|greenhouse|lever|workday|myworkday|"
                        r"smartrecruiters|pageuppeople|pageup|successfactors|taleo|icims|jobadder|employmenthero|"
                        r"applynow|bamboohr|recruitee|recruitee-mailbox|ashbyhq|teamtailor|livehire|google|microsoft|youtube|"
                        r"facebook|instagram|twitter|x|apple|gov|example)\.", re.I)
_ANONYMOUS = re.compile(r"^\s*$|private advertiser|confidential|undisclosed|anonymous", re.I)
_JUNIOR = re.compile(r"\b(junior|entry[- ]level|no experience (needed|required|necessary))\b", re.I)
_NAME_DROP = {"pty", "ltd", "limited", "the", "australia", "australian", "group", "holdings", "services",
              "company", "co", "inc", "and", "of", "au", "com", "net", "org"}

LEVELS = (("high", 50), ("medium", 25), ("low", 0))


# ---- configuration ----

def settings(config: dict) -> dict:
    raw = config.get("authenticity") if isinstance(config, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    data_dir = Path(raw.get("data_dir") or "data/authenticity")
    return {"enabled": raw.get("enabled") is True,
            "check_domains": raw.get("check_domains", True) is not False,
            "data_dir": data_dir if data_dir.is_absolute() else ROOT / data_dir,
            "refresh_days": int(raw.get("refresh_days") or DEFAULT_REFRESH_DAYS)}


def enabled(config: dict) -> bool:
    return settings(config)["enabled"]


# ---- text helpers ----

def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _snippet(text: str, start: int, end: int, width: int = 70) -> str:
    left, right = max(0, start - width), min(len(text), end + width)
    return ("…" if left else "") + text[left:right].strip() + ("…" if right < len(text) else "")


def scan_signs(text: str) -> list[dict]:
    """Warning signs found in the ad text, each with its quoted evidence."""
    text = _clean(text)
    found = []
    for key, points, pattern in SIGNS:
        for m in pattern.finditer(text):
            if _NEGATION.search(text[max(0, m.start() - 40):m.start()]):
                continue
            if key in _SENTENCE_GUARDED and _WARNING_SENTENCE.search(_sentence(text, m.start(), m.end())):
                continue
            found.append({"key": key, "points": points, "text": _snippet(text, m.start(), m.end())})
            break
    return found


def _sentence(text: str, start: int, end: int) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("! ", 0, start), text.rfind("? ", 0, start)) + 1
    stops = [i for i in (text.find(". ", end), text.find("! ", end), text.find("? ", end)) if i >= 0]
    return text[left:min(stops) if stops else len(text)]


def email_domains(text: str) -> list[str]:
    """Domains of email addresses in the ad: the contact channel the employer chose."""
    return sorted({m.group(1).lower().rstrip(".") for m in _EMAIL.finditer(text or "")})


def contact_domains(text: str) -> list[str]:
    """Email and web domains in the ad (for the DNS check)."""
    domains = set(email_domains(text))
    domains |= {m.group(1).lower().rstrip(".") for m in _URL.finditer(text or "")}
    # a real top-level domain has 2+ letters ("L.E.K." in prose is not a domain)
    return sorted(d for d in domains if re.search(r"\.[a-z]{2,}$", d))


_SUFFIXES = ("vic.edu.au", "nsw.edu.au", "qld.edu.au", "wa.edu.au", "sa.edu.au", "com.au", "net.au", "org.au",
             "edu.au", "gov.au", "asn.au", "id.au", "co.uk", "org.uk", "co.nz", "org.nz")


def _brand_label(domain: str) -> str:
    """The registrable label: "au.example.com" -> "example", "admin.ex.vic.edu.au" -> "ex"."""
    labels = domain.lower().split(".")
    for suffix in _SUFFIXES:
        if domain.lower().endswith("." + suffix):
            rest = labels[:-len(suffix.split("."))]
            return rest[-1] if rest else ""
    return labels[-2] if len(labels) >= 2 else labels[0]


def registrable(domain: str) -> str:
    """"au.example.com" -> "example.com", "admin.ex.vic.edu.au" -> "ex.vic.edu.au"."""
    labels = domain.lower().split(".")
    for suffix in _SUFFIXES:
        if domain.lower().endswith("." + suffix):
            size = len(suffix.split(".")) + 1
            return ".".join(labels[-size:])
    return ".".join(labels[-2:])


def _exists(domain: str, resolver) -> bool:
    """Mail-only subdomains often have no address record, so the parent and its www count too."""
    parent = registrable(domain)
    for candidate in dict.fromkeys((domain, parent, "www." + parent)):
        try:
            if resolver(candidate):
                return True
        except (OSError, UnicodeError):
            continue
    return False


def domain_matches_company(domain: str, company: str) -> bool:
    label = _brand_label(domain)
    words = re.findall(r"[a-z0-9]+", (company or "").lower().replace("&", " "))
    tokens = [w for w in words if w not in _NAME_DROP and len(w) >= 2]
    squashed = "".join(words)
    initials = "".join(w[0] for w in words if w not in {"the", "of", "and", "pty", "ltd", "limited"})
    return bool(label) and (any(t in label or label in t for t in tokens if len(t) >= 3 or t == label)
                            or (len(label) > 3 and label in squashed)
                            or (len(label) >= 2 and label in initials))


# ---- domain lookups (fetch stage) ----

def _domains_path(cfg: dict) -> Path:
    return cfg["data_dir"] / "domains.json"


def _load_domains(cfg: dict) -> dict:
    try:
        return json.loads(_domains_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def refresh(conn, config: dict, resolver=None) -> int:
    """Fetch-stage only: DNS-check domains quoted in ads that are new or stale. Returns lookups done."""
    cfg = settings(config)
    if not (cfg["enabled"] and cfg["check_domains"]):
        return 0
    resolver = resolver or (lambda d: bool(socket.getaddrinfo(d, None)))
    cache = _load_domains(cfg)
    now = datetime.now(timezone.utc)
    wanted: set[str] = set()
    for (text,) in conn.execute("SELECT COALESCE(description, teaser, '') FROM jobs"):
        for domain in contact_domains(text):
            if domain in _FREEMAIL or _PLATFORMS.search(domain + "."):
                continue
            entry = cache.get(domain)
            if entry:
                age = (now - datetime.fromisoformat(entry["checked_at"])).days
                if age < cfg["refresh_days"]:
                    continue
            wanted.add(domain)
    done = 0
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        for domain in sorted(wanted)[:MAX_LOOKUPS_PER_FETCH]:
            cache[domain] = {"resolves": _exists(domain, resolver), "checked_at": now.isoformat(timespec="seconds")}
            done += 1
    finally:
        socket.setdefaulttimeout(previous)
    if done:
        path = _domains_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
    return done


# ---- the assessment ----

def _level(risk: int) -> str:
    return next(name for name, floor in LEVELS if risk >= floor)


def assess(job: dict, *, domains: dict, duplicates: int, employer: dict) -> dict:
    """job: title / company / description / annual_max / hourly flag; employer: established-employer hints.

    Returns {"risk": 0-100, "level": low|medium|high, "reasons": [(key, params, points)]}.
    """
    text = _clean(job.get("description") or job.get("teaser"))
    company = job.get("company") or ""
    reasons: list[tuple[str, dict, int]] = []

    for sign in scan_signs(text):
        reasons.append((f"auth.r_{sign['key']}", {"quote": sign["text"]}, sign["points"]))

    # Only email domains are compared with the employer: links in an ad are often press,
    # partners or parent companies. Every quoted domain gets the existence check.
    emails = email_domains(text)
    for domain in emails:
        if domain in _FREEMAIL:
            reasons.append(("auth.r_freemail", {"domain": domain}, 15))
        elif _PLATFORMS.search(domain) or not company:
            continue
        elif domain_matches_company(domain, company):
            reasons.append(("auth.r_domain_match", {"domain": domain}, -5))
        else:
            reasons.append(("auth.r_domain_mismatch", {"domain": domain}, 10))
    for domain in contact_domains(text):
        # Only address records can be checked with the standard library, so a mail-only
        # domain can look missing: a modest weight, not a verdict.
        if domain not in _FREEMAIL and domains.get(domain, {}).get("resolves") is False:
            reasons.append(("auth.r_domain_missing", {"domain": domain}, 10))

    if _ANONYMOUS.search(company):
        reasons.append(("auth.r_anonymous", {}, 10))
    top = job.get("annual_max") or 0
    if top >= 150_000 and _JUNIOR.search(f"{job.get('title') or ''} {text[:600]}"):
        reasons.append(("auth.r_pay_anomaly", {"salary": f"{top:,.0f}"}, 15))
    if text and len(text) < 300:
        reasons.append(("auth.r_thin", {}, 5))
    # Groups and their brands often share one ad, so only flag wider copy-pasting.
    if duplicates >= 4:
        reasons.append(("auth.r_cross_posted", {"n": duplicates}, 15))

    if employer.get("accredited"):
        reasons.append(("auth.r_accredited", {}, -15))
    if employer.get("listed"):
        reasons.append(("auth.r_listed", {}, -15))

    risk = max(0, min(100, BASE + sum(points for _, _, points in reasons)))
    return {"risk": risk, "level": _level(risk), "reasons": reasons}


def _employer_hints(config: dict) -> dict[str, dict]:
    """Established-employer hints per job from the sponsorship add-on's results, if it is present.

    Reads the add-on's result file through its own loader; absent add-on or results = no hints.
    """
    loaders = []
    for name in ("sponsorship", "sponsors"):
        try:
            module = __import__(f"{__package__}.{name}", fromlist=["load_results"])
            loaders.append(module.load_results)
        except ImportError:
            continue
    for load in loaders:
        try:
            results = load(config) or {}
        except Exception:                 # noqa: BLE001 - hints are optional
            continue
        if results:
            hints = {}
            for uid, entry in results.items():
                keys = {r[0] for r in ((entry.get("fit") or {}).get("reasons") or [])}
                hints[uid] = {"accredited": entry.get("acc") == "exact",
                              "listed": bool(keys & {"fit.r_asx", "fit.r_ato"})}
            return hints
    return {}


def check_all(conn, config: dict) -> dict[str, dict]:
    cfg = settings(config)
    domains = _load_domains(cfg)
    hints = _employer_hints(config)
    rows = conn.execute(
        "SELECT j.uid, j.title, j.company, j.description, j.teaser, sal.annual_max "
        "FROM jobs j LEFT JOIN salary sal ON sal.uid = j.uid").fetchall()
    # The same ad body under several different employer names is a known copy-paste pattern.
    companies_by_body: dict[str, set[str]] = {}
    for _uid, _title, company, description, _teaser, _salary in rows:
        body = _clean(description).lower()
        if len(body) >= 300:
            digest = hashlib.sha1(body.encode("utf-8")).hexdigest()
            companies_by_body.setdefault(digest, set()).add((company or "").strip().lower())
    results = {}
    for uid, title, company, description, teaser, annual_max in rows:
        body = _clean(description).lower()
        digest = hashlib.sha1(body.encode("utf-8")).hexdigest() if len(body) >= 300 else None
        duplicates = len(companies_by_body.get(digest, ())) if digest else 0
        job = {"title": title, "company": company, "description": description, "teaser": teaser,
               "annual_max": annual_max}
        results[uid] = assess(job, domains=domains, duplicates=duplicates, employer=hints.get(uid, {}))
    return results


def results_path(config: dict) -> Path:
    return db_path(config).resolve().parent / RESULTS_NAME


def run(conn, config: dict) -> dict | None:
    """After a successful analyze. Offline; writes only the side file."""
    if not enabled(config):
        return None
    results = check_all(conn, config)
    payload = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "results": results}
    path = results_path(config)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    levels = [r["level"] for r in results.values()]
    print("[authenticity] scam risk: " + " | ".join(f"{k} {levels.count(k)}" for k in ("high", "medium", "low")))
    return payload


_CACHE: dict[str, tuple[float, dict]] = {}


def load_results(config: dict) -> dict[str, dict]:
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
