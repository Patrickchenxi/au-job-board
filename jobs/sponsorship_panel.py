"""Panel rendering for the optional sponsorship add-on (``jobs/sponsorship.py``).

Nothing here renders unless ``attach`` found results, i.e. ``sponsorship.enabled``
is true and ``analyze`` has run since. Existing card tags and cues are untouched;
the add-on only appends its own tags and one detail block, in this order:

1. can the employer definitely sponsor (accredited list / the ad says so),
2. sponsorship likelihood (a label-style meter with the points behind it),
3. what the ad says about sponsorship or work rights.
"""
from __future__ import annotations

from html import escape

from . import i18n
from . import sponsorship
from . import sponsorship_fit

ROW_KEY = "_sponsorship"

# Label-style meter; the mark is a plain green square with a gold tick.
_MARK = ('<svg class="aumark" viewBox="0 0 20 20" aria-hidden="true">'
         '<rect width="20" height="20" rx="4" fill="#00843D"/>'
         '<path d="M5 10.5l3.2 3.2L15 6.8" fill="none" stroke="#FFCD00" stroke-width="2.6" '
         'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def _tag(kind: str, text: str, title: str | None = None) -> str:
    tip = f' title="{_e(title)}"' if title else ""
    return f'<span class="tag {kind}"{tip}>{_e(text)}</span>'


def attach(rows, config: dict) -> None:
    """Add ``_sponsorship`` to each row when the add-on is enabled and has results."""
    results = sponsorship.load_results(config)
    if not results:
        return
    for row in rows:
        row[ROW_KEY] = results.get(row["uid"]) or {}


def _certain(s: dict) -> bool:
    fit = s.get("fit") or {}
    if "certain" in fit:
        return bool(fit["certain"])
    return (s.get("acc") == "exact" or s.get("ad") == "offers") and s.get("sanction_level") != "confirmed"


def meter(fit: dict, lang: str, *, large: bool = False, title: str | None = None) -> str:
    T = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    p = int(fit.get("likelihood") or 0)
    tip = f' title="{_e(title)}"' if title else ""
    bar = (f'<span class="aumeter-bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{p}" '
           f'aria-label="{_e(T("fit.meter"))}"><i style="width:{p}%"></i></span>')
    if not large:
        return (f'<span class="aumeter m-{fit["rating"]}"{tip}>{_MARK}'
                f'<span class="aumeter-body"><span class="aumeter-text">{_e(T("fit.meter_short", p=p))}</span>'
                f'{bar}</span></span>')
    return (f'<div class="aumeter large m-{fit["rating"]}"{tip}>{_MARK}'
            f'<div class="aumeter-body"><div class="aumeter-text">{_e(T("fit.meter_long", p=p))}</div>{bar}'
            f'<div class="aumeter-scale" aria-hidden="true"><span>0%</span><span>50%</span><span>100%</span></div>'
            f'<div class="aumeter-caption">{_e(T("fit." + fit["rating"]))}</div></div></div>')


def card_tags(row: dict, lang: str) -> str:
    if ROW_KEY not in row:
        return ""
    s = row[ROW_KEY]
    T = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    out = ""
    if _certain(s):
        tip = (T("sponsor.tip_acc", name=s.get("acc_name") or "") if s.get("acc") == "exact"
               else s.get("ad_text") or "")
        out += _tag("sponsor certain", T("fit.certain_yes"), tip)
    if (fit := s.get("fit")):
        out += meter(fit, lang, title=T("fit.tip"))
    if s.get("ad") == "pr_only":
        out += _tag("bad", T("sponsor.pr_only"), s.get("ad_text"))
    elif s.get("ad") == "no":
        out += _tag("warn", T("sponsor.no"), s.get("ad_text"))
    if (hit := s.get("sanction")):
        tip = T("sponsor.tip_sanction", name=hit.get("name") or "", trading=hit.get("trading") or "",
                sanction=hit.get("sanction") or "", date=hit.get("date") or "", end=hit.get("end") or "—")
        if s.get("sanction_level") == "confirmed":
            out += _tag("bad", T("sponsor.sanction"), tip)
        else:
            out += _tag("warn", T("sponsor.sanction_possible"), T("sponsor.tip_possible") + "\n" + tip)
    if s.get("acc") == "fuzzy":
        out += _tag("sponsor maybe", T("sponsor.acc_fuzzy"), T("sponsor.tip_fuzzy", name=s.get("acc_name") or ""))
    if s.get("agency"):
        out += _tag("adjust", T("sponsor.agency"), T("sponsor.tip_agency"))
    return out


def detail_block(row: dict, lang: str) -> str:
    if ROW_KEY not in row:
        return ""
    s = row[ROW_KEY]
    T = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731

    def section(n: int, title: str, head: str, lines: list[str], body: str = "") -> str:
        items = "".join(f"<li>{_e(line)}</li>" for line in lines)
        return (f'<div class="fit-sec"><div class="fit-head"><span class="step">{n}</span><b>{_e(title)}</b>{head}</div>'
                + body + (f"<ul>{items}</ul>" if items else "") + "</div>")

    # 1. can the employer definitely sponsor
    certain = _certain(s)
    lines = []
    if s.get("acc"):
        lines.append(T(f"sponsor.line_acc_{s['acc']}", name=s.get("acc_name") or ""))
    if s.get("ad") == "offers":
        lines.append(T("sponsor.line_offers") + f"“{s.get('ad_text') or ''}”")
    if (hit := s.get("sanction")):
        key = "sponsor.line_sanction" if s.get("sanction_level") == "confirmed" else "sponsor.line_sanction_possible"
        lines.append(T(key, name=hit.get("name") or "", trading=hit.get("trading") or "",
                       sanction=hit.get("sanction") or "", date=hit.get("date") or "", end=hit.get("end") or "—"))
    if s.get("agency"):
        lines.append(T("sponsor.tip_agency"))
    if not lines:
        lines.append(T("sponsor.line_none"))
    head = _tag("sponsor certain" if certain else "adjust", T("fit.certain_yes" if certain else "fit.certain_no"))
    out = section(1, T("fit.sec_certain"), head, lines)

    # 2. likelihood
    if (fit := s.get("fit")):
        reasons = [T("fit.base", base=sponsorship_fit.LIKELIHOOD_BASE)]
        for key, params, points in fit.get("reasons") or []:
            text = T(key, **params)
            reasons.append(f"{text} ({points:+d})" if points else text)
        out += section(2, T("fit.sec_likelihood"), "", reasons, body=meter(fit, lang, large=True))
    else:
        out += section(2, T("fit.sec_likelihood"), "", [T("fit.not_rated")])

    # 3. what the ad says
    if s.get("ad") in ("pr_only", "no", "offers"):
        kind = {"pr_only": "bad", "no": "warn", "offers": "sponsor"}[s["ad"]]
        lines = [T(f"sponsor.line_{s['ad']}") + f"“{s.get('ad_text') or ''}”"]
        out += section(3, T("fit.sec_ad"), _tag(kind, T(f"fit.ad_{s['ad']}")), lines)
    else:
        out += section(3, T("fit.sec_ad"), "", [T("fit.ad_none")])

    return (f'<div class="sponsor-check">{out}'
            f'<div class="hint">{_e(T("fit.note"))} {_e(T("sponsor.note"))}</div></div>')
