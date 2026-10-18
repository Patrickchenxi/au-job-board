"""经验年限规则的回归测试（双向，合成数据）。

背景：级别规则原来有一条抓「N years experience」的正则，但等级判定只把
标题传进去，而真正的年限要求几乎全在正文的 Requirements 段。改成读正文后，
误判风险从「漏」翻转到「错」：正文里到处是**企业叙述句**（"more than 30
years of experience" 之类），直接搜就会把它们当成岗位要求。

所以这个脚本必须双向断言：
  - PENALTY：要求语境下的年限句，必须扣分（并核对档位）
  - NO_PENALTY：企业叙述、毕业生资格窗口、年限上限句，必须**不**扣分

本文件中的正文与标题全部是**为测试手写的最小合成句**，不含真实公司、
岗位、项目或从语料摘录的原文；固定 expected 由人工写死，不用被测函数反推。
数据政策与覆盖映射见 docs/test-data-policy.md。

用法（不联网、不写库）：
    .venv/bin/python tools/test_experience_rules.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobs.config import load_rules                    # noqa: E402
from jobs.filters import normalize_text               # noqa: E402
from jobs.scoring import score_experience, score_job  # noqa: E402

# (合成 ID, 场景标签, 正文片段, 期望分数)
PENALTY = [
    ("synthetic_experience_001", "minimum 5 years + 要求语境",
     "Essential experience required. Minimum 5 years of hands-on platform operations.",
     -3),
    ("synthetic_experience_002", "minimum 10 years + experience",
     "**Qualifications:** * Minimum 10 years of experience in software engineering.",
     -3),
    ("synthetic_experience_003", "at least 1–3 years（区间取下界 1，最轻一档）",
     "What we're looking for: at least 1–3 years of experience in a similar role.",
     -1),
    ("synthetic_experience_004", "you have / 要求语境 + 5+ years experience",
     "You should have: 5+ years experience shipping production code.",
     -3),
    ("synthetic_experience_005", "Experience 在数字前，4–8 years 字段式表达",
     "**Location:** Northwind **Experience:** 4–8 years **Employment Type:** Contract",
     -2),
    ("synthetic_experience_006", "experience 在前，(7+ years) 括号表达",
     "Demonstrated experience in a comparable technical role (7+ years) hands-on "
     "experience with modern tooling.",
     -3),
    ("synthetic_experience_007", "minimum of 1 year，单数 year",
     "REQUIREMENTS Essential Skills: * Minimum of 1 year experience in a support role.",
     -1),
    ("synthetic_experience_008", "2 years (Required)，要求词在数字后",
     "Diploma (Required) Experience: * help desk: 2 years (Required) Language: English.",
     -1),
    ("synthetic_experience_009", "5yrs+ 缩写",
     "Technical Skills: Demonstrated experience 5yrs+ maintaining cloud platforms.",
     -3),
    ("synthetic_experience_010", "minimum 3 years，句里没有 experience 一词",
     "To succeed you will need: Minimum 3 years in a similar role plus stakeholder skills.",
     -2),
    ("synthetic_experience_011", "5 – 10 years（区间取下界）",
     "In advanced roles, 5 – 10 years experience delivering core services.",
     -3),
    ("synthetic_experience_012", "3 to 5 years（区间取下界）",
     "### **Essential** * 3 to 5 years building production services.",
     -2),
    ("synthetic_experience_013", "字面含转义反斜杠的 3 \\- 5 years + preferred",
     "Preferred if you have 3 \\- 5 years of experience in service support.",
     -2),
    ("synthetic_experience_014", "you will bring / at least 3 years + 弯引号",
     "**What you will bring:** * At least 3 years’ experience in operations support.",
     -2),
]

# 这些**不能**扣分 —— 全是合成版的企业叙述 / 资格窗口 / 上限句
NO_PENALTY = [
    ("synthetic_experience_015", "企业历史 has more than 30 years of experience",
     "About Northwind Northwind has more than 30 years of experience delivering "
     "advisory services."),
    ("synthetic_experience_016", "团队宣传 With 35+ years of experience, we ...",
     "We stay ahead of the market. With 35+ years of experience, we guide and mentor "
     "new talent."),
    ("synthetic_experience_017", "we have ... 15 years of experience ...，团队叙述",
     "We have a long history. We have a clear plan, 15 years of experience and are "
     "expanding."),
    ("synthetic_experience_018", "企业介绍 with over 20 years of experience",
     "Northwind is an award-winning data company with over 20 years of experience "
     "delivering analytics solutions."),
    ("synthetic_experience_019", "团队/业务叙述 backed by over 20 years of experience",
     "Platform delivery, cloud services and data engineering, all backed by over 20 "
     "years of experience."),
    ("synthetic_experience_020", "机构介绍 with over 40 years of experience",
     "The College is a leading provider of technical education, with over 40 years of "
     "experience and many graduates."),
    ("synthetic_experience_021", "graduated within the last 4 years（毕业资格窗口）",
     "To be eligible for the graduate intake, a participant must complete their studies "
     "and graduate within the last 4 years."),
    ("synthetic_experience_022", "8 - 11 years 描述课程分组（跟经验无关）",
     "Our new curriculum spans a vertical structure across the traditional 8 - 11 years "
     "called our core program."),
    ("synthetic_experience_023", "less than 1 year left（学历剩余时长）",
     "Candidates with a recently completed diploma (or less than 1 year left)."),
    ("synthetic_experience_024", "candidates with up to 5 years（上限句）",
     "**Who May Apply** Candidates with up to 5 years of relevant work experience."),
    ("synthetic_experience_025", "has up to 2 years of experience（上限）",
     "This role suits someone who has up to 2 years of experience and wants to grow."),
    ("synthetic_experience_026", "less than 3 years’ experience（说的是「够年轻也行」）",
     "For people with less than 3 years’ experience, show us your best work."),
    ("synthetic_experience_027", "working rights for a minimum of 2 years（工作权有效期）",
     "This role requires working rights in Australia for a minimum of 2 years."),
    ("synthetic_experience_028", "work alongside engineers with 10+ years（同事经验）",
     "You will work alongside engineers who have 10+ years of experience in the team."),
    ("synthetic_experience_029", "企业历史 over 175 years（保留三位数形状）",
     "Delivered with world-leading expertise and over 175 years of experience in "
     "community care."),
]

# (合成 ID, 场景标签, 标题, 期望分数)
TITLE = [
    ("synthetic_experience_030", "标题中的 5+ years experience required",
     "Senior Platform Engineer (5+ years experience required)", -3),
]


# 标题与正文都保留既有守卫，取有效要求的最大值。
COMBINED = [
    ("body_higher", "Engineer (2 years Python experience)",
     "Minimum 5 years of software engineering experience required.", -3, 5),
    ("title_higher", "Engineer (5 years experience)",
     "Minimum 2 years of Python experience required.", -3, 5),
    ("body_denied", "Engineer (2 years experience)",
     "Our team has over 30 years of experience delivering services.", -1, 2),
    ("body_unrelated", "Engineer (2 years experience)",
     "The equipment warranty lasts 5 years.", -1, 2),
    ("body_range", "Engineer (1 year Python experience)",
     "Minimum 3 to 5 years of software engineering experience required.", -2, 3),
]


def main() -> int:
    rules = load_rules()
    failures: list[str] = []
    print(f"规则版本 {rules.get('version')}　"
          f"（experience.buckets={rules.get('experience', {}).get('buckets')}）\n")

    print("\n== 必须扣分（PENALTY，正文）==")
    for cid, label, text, want in PENALTY:
        got, reasons = score_experience("", normalize_text(text), rules)
        ok = got == want
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid} {label}　期望 {want:+d}，实际 {got:+d}")
        if not ok:
            failures.append(f"{cid} {label}: 期望 {want:+d}，实际 {got:+d} {reasons}")
        elif reasons:
            print(f"          -> {reasons[0]}")

    print("\n== 必须不扣分（NO_PENALTY，正文）==")
    for cid, label, text in NO_PENALTY:
        got, reasons = score_experience("", normalize_text(text), rules)
        ok = got == 0
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid} {label}　实际 {got:+d}")
        if not ok:
            failures.append(f"{cid} {label}: 被误判为要求 {got:+d} {reasons}")

    print("\n== 标题里的年限直接算要求（TITLE）==")
    for cid, label, title, want in TITLE:
        got, _ = score_experience(normalize_text(title), "", rules)
        ok = got == want
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid} {label}　期望 {want:+d}，实际 {got:+d}")
        if not ok:
            failures.append(f"{cid} {label}: 期望 {want:+d}，实际 {got:+d}")

    print("\n== 标题与正文的有效最大要求（COMBINED）==")
    for cid, title, body, want, years in COMBINED:
        got, reasons = score_experience(title, body, rules)
        job = {"title": title, "description": body, "classification": "",
               "job_level": "", "location": ""}
        scored = score_job(job, rules)
        expected_reason = f"experience:{years}y {want:+d}"
        ok = (got == want and reasons == [expected_reason]
              and scored["level_score"] == want
              and expected_reason in scored["reasons"])
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid}: {got:+d} {reasons}")
        if not ok:
            failures.append(f"{cid}: expected {want} / {expected_reason}, got {scored}")

    print()
    if failures:
        print(f"失败 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 2
    print(f"全部通过（{len(PENALTY)} 条必须扣分 + {len(NO_PENALTY)} 条必须不扣分 "
          f"+ {len(TITLE)} 条标题 + {len(COMBINED)} 条组合）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
