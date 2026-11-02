"""Panel rendering for the optional scam-risk add-on (``jobs/authenticity.py``).

Renders nothing unless ``attach`` found results (``authenticity.enabled`` and
``analyze`` has run since). Cards get a badge only for medium / high risk; the job
detail gets one compact row whose evidence opens on hover or focus. The add-on
keeps its own strings so it can be added or removed without touching i18n.py.
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote_plus

from . import authenticity

ROW_KEY = "_authenticity"
SCAMWATCH_URL = "https://www.scamwatch.gov.au/types-of-scams/jobs-and-employment-scams"
ABN_LOOKUP_URL = "https://abr.business.gov.au/Search/ResultsActive?SearchText="
SEARCH_URL = "https://www.google.com/search?q="

TEXT = {
    "en": {
        "badge": "Scam risk {risk}%",
        "level.high": "High scam risk", "level.medium": "Some scam signs", "level.low": "No scam signs found",
        "row": "Is this ad genuine?",
        "base": "Starting point {base}%",
        "check": "Check it yourself:",
        "link.site": "Find the employer's own site",
        "link.abn": "ABN Lookup",
        "link.scamwatch": "Scamwatch: job scams",
        "note": "A pointer from the ad text and public signals, not a verdict. Most scams start after you apply: "
                "never pay to get a job, keep contact on the employer's own channels, and don't send ID or bank "
                "details before you have checked the employer independently.",
        "r_upfront_payment": "Asks you to pay (fee, kit, training…)",
        "r_crypto_topup": "Mentions crypto or topping up an account",
        "r_money_mule": "Receiving or forwarding money or parcels for someone else",
        "r_task_scam": "Paid 'tasks' such as liking, rating or 'optimising' apps",
        "r_messaging_app": "Contact through WhatsApp / Telegram / similar",
        "r_id_early": "Asks for ID or bank details up front",
        "r_no_interview": "Hiring without an interview",
        "r_easy_money": "High pay for little effort",
        "r_mlm": "'Be your own boss' / recruit-others wording",
        "r_urgency": "Pressure to act fast",
        "r_freemail": "Uses a personal email address ({domain})",
        "r_domain_mismatch": "Contact domain {domain} does not match the employer's name",
        "r_domain_match": "Contact domain {domain} matches the employer's name",
        "r_domain_missing": "Contact domain {domain} does not exist (DNS lookup)",
        "r_anonymous": "Employer name hidden",
        "r_pay_anomaly": "Unusually high pay (${salary}) for a junior / entry role",
        "r_thin": "Very short ad",
        "r_cross_posted": "Same ad text posted under {n} different employer names",
        "r_accredited": "Employer is on the Home Affairs accredited sponsor list",
        "r_listed": "Employer is ASX-listed or in the ATO large-company report",
    },
    "zh": {
        "badge": "诈骗风险 {risk}%",
        "level.high": "诈骗风险高", "level.medium": "有可疑迹象", "level.low": "未发现诈骗迹象",
        "row": "这则广告可信吗",
        "base": "起点 {base}%",
        "check": "自己核实：",
        "link.site": "自己搜雇主官网",
        "link.abn": "ABN 查询",
        "link.scamwatch": "Scamwatch 求职诈骗说明",
        "note": "这是根据广告原文和公开信息给出的提示，不是结论。多数诈骗发生在投递之后：不要为求职付钱，"
                "只通过雇主自己的渠道联系，在独立核实雇主之前不要发送证件或银行信息。",
        "r_upfront_payment": "要求你付钱（费用、工具包、培训等）",
        "r_crypto_topup": "提到加密货币或给账户充值",
        "r_money_mule": "替别人收款、转账或转寄包裹",
        "r_task_scam": "做「任务」赚钱，比如点赞、评分、「优化」应用",
        "r_messaging_app": "通过 WhatsApp / Telegram 等聊天软件联系",
        "r_id_early": "一开始就要证件或银行信息",
        "r_no_interview": "不面试直接录用",
        "r_easy_money": "轻松高薪",
        "r_mlm": "「做自己的老板」/ 拉人头式的说法",
        "r_urgency": "催你赶快行动",
        "r_freemail": "使用个人邮箱（{domain}）",
        "r_domain_mismatch": "联系域名 {domain} 和雇主名称对不上",
        "r_domain_match": "联系域名 {domain} 和雇主名称一致",
        "r_domain_missing": "联系域名 {domain} 不存在（DNS 查询）",
        "r_anonymous": "雇主名称被隐藏",
        "r_pay_anomaly": "初级 / 入门岗位薪资异常高（${salary}）",
        "r_thin": "广告内容很短",
        "r_cross_posted": "同一段广告文字出现在 {n} 个不同的雇主名下",
        "r_accredited": "雇主在 Home Affairs 认证担保名单上",
        "r_listed": "雇主是 ASX 上市公司，或在 ATO 大企业名单里",
    },
}


def _t(lang: str, key: str, **params) -> str:
    text = TEXT.get(lang, TEXT["en"]).get(key) or TEXT["en"].get(key) or key
    return text.format(**params) if params else text


def _e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def attach(rows, config: dict) -> None:
    results = authenticity.load_results(config)
    if not results:
        return
    for row in rows:
        if row["uid"] in results:
            row[ROW_KEY] = results[row["uid"]]


def card_tags(row: dict, lang: str) -> str:
    result = row.get(ROW_KEY)
    if not result or result["level"] == "low":
        return ""
    title = _t(lang, f"level.{result['level']}")
    return (f'<span class="tag ar-badge ar-{result["level"]}" title="{_e(title)}">'
            f'<span aria-hidden="true">⚠</span> {_e(_t(lang, "badge", risk=result["risk"]))}</span>')


def detail_block(row: dict, lang: str) -> str:
    result = row.get(ROW_KEY)
    if not result:
        return ""
    lines = [_t(lang, "base", base=authenticity.BASE)]
    for key, params, points in result.get("reasons") or []:
        quote = params.get("quote")
        text = _t(lang, key.split(".", 1)[1], **{k: v for k, v in params.items() if k != "quote"})
        lines.append(f"{text} ({points:+d})" + (f" — “{quote}”" if quote else ""))
    company = row.get("company") or ""
    links = (f'<a href="{_e(SEARCH_URL + quote_plus(company + " official site careers"))}" target="_blank" rel="noopener">'
             f'{_e(_t(lang, "link.site"))} ↗</a> · '
             f'<a href="{_e(ABN_LOOKUP_URL + quote_plus(company))}" target="_blank" rel="noopener">'
             f'{_e(_t(lang, "link.abn"))} ↗</a> · '
             f'<a href="{_e(SCAMWATCH_URL)}" target="_blank" rel="noopener">{_e(_t(lang, "link.scamwatch"))} ↗</a>')
    items = "".join(f"<li>{_e(line)}</li>" for line in lines)
    level = result["level"]
    head = (f'<span class="tag ar-badge ar-{level}">'
            f'{_e(_t(lang, f"level.{level}"))} · {result["risk"]}%</span>')
    return (f'<div class="ar-block"><span class="ar-row"><b>{_e(_t(lang, "row"))}</b>'
            f'<span class="ar-wrap" tabindex="0" aria-describedby="ar-pop">{head}'
            f'<span class="ar-i" aria-hidden="true">ⓘ</span>'
            f'<span class="ar-pop" role="tooltip" id="ar-pop"><ul>{items}</ul>'
            f'<span class="ar-links">{_e(_t(lang, "check"))} {links}</span>'
            f'<span class="ar-foot">{_e(_t(lang, "note"))}</span></span></span></span></div>')
