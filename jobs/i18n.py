"""面板的界面语言层（中文 / English）。

**只管界面文案**：按钮、筛选、提示、空状态、错误反馈和页面 lang 声明。
以下内容的存储值不随语言切换而改变：

  - 岗位正文、公司名、地点、资格原文摘录
  - 用户备注、标注与投递记录；默认备注标签仅在显示层翻译，自定义备注原样显示
  - 技能规范名与别名（同时用于提取、搜索与编辑）
  - 数据库里的英文枚举（eligible / want / saved …）—— 显示名在这里，存储值不迁移
  - render.py 里的资格线索名（「公民/PR」等）是内部键，这里只做显示映射

语言选择：cookie `jobs_lang`（zh / en）> 浏览器 Accept-Language > 中文。
外观：cookie `jobs_theme`（light / dark），没有就跟随系统。
"""

from __future__ import annotations

import re

LANGS = ("zh", "en")
DEFAULT_LANG = "zh"
LANG_COOKIE = "jobs_lang"
THEME_COOKIE = "jobs_theme"
THEMES = ("light", "dark")
HTML_LANG = {"zh": "zh-CN", "en": "en"}

STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        # 页面与顶栏
        "app.title": "澳洲岗位面板",
        "settings.title": "设置",
        "nav.views": "视图",
        "nav.menu": "打开菜单",
        "nav.menu_close": "关闭菜单",
        "nav.settings": "设置",
        "nav.settings_hint": "资格、抓取、技能、显示",
        "nav.back": "返回面板",
        "lang.current": "中文",
        "lang.other": "EN",
        "lang.switch": "Switch to English",
        "theme.to_dark": "切换到深色模式",
        "theme.to_light": "切换到浅色模式",
        # 视图
        "view.recommend": "推荐",
        "view.all": "全部",
        "view.new": "新增",
        "view.excluded": "被排除",
        "view.labelled": "已标注",
        "viewhint.recommend": "未标注，分数优先",
        "viewhint.all": "全库，含被排除的",
        "viewhint.new": "最近一次抓取",
        "viewhint.excluded": "按规则分组",
        "viewhint.labelled": "你标过的",
        "viewdesc.recommend": "还没标注的岗位，分数高的在前；每 10 条混入 1 条低分岗位做校准。挂出超过 30 天的不进这里。",
        "viewdesc.all": "去重后的全部岗位，也包括被规则排除的（卡片上标「已排除」）。",
        "viewdesc.new": "最近一次抓取新增的岗位，包括被排除的。",
        "viewdesc.excluded": "被硬规则排除的岗位，按规则分组。怀疑排错了（漏杀 / 误杀），就在这里找。",
        "viewdesc.labelled": "你标注过的岗位，包括被排除的。勾上「只看优先投递」就是待投队列。",
        # 统计
        "stat.labelled": "已标注",
        "stat.saved": "待投",
        "stat.applied": "已投递",
        "stat.miss": "标了不可投但未排除",
        "stat.false_excl": "已排除但标了可投",
        "stat.batch": "本批",
        "stat.rules": "条被排除",
        # 搜索与筛选
        "search.placeholder": "搜索标题、公司、地点、备注、tag、正文…",
        "search.label": "搜索",
        "search.explain": "搜索：<b>{query}</b> → {terms}{all}，共 {total} 条",
        "search.all_match": "（全部满足）",
        "term.skill": "技术词「{label}」",
        "term.prefix": "前缀「{label}」",
        "term.word": "整词「{label}」",
        "filter.more": "更多筛选",
        "filter.button": "筛选",
        "filter.done": "完成",
        "filter.clear_hidden": "清除这些筛选",
        "filter.clear_all": "清除全部筛选",
        "filter.active": "已启用：",
        "filter.remove": "移除筛选",
        "filter.group.label": "标注",
        "filter.group.label_hint": "按你的判断筛",
        "filter.group.job": "岗位条件",
        "filter.group.job_hint": "按岗位本身筛",
        "filter.any": "不限",
        "filter.none": "未标这一项",
        "filter.salary": "只看标了薪资的",
        "filter.salary_chip": "有薪资",
        "filter.fresh": "只看 30 天内的",
        "filter.priority": "只看优先投递",
        "filter.skill": "技能",
        "filter.skill_hint": "任一命中",
        "filter.tier": "层级",
        "filter.sort": "排序",
        "filter.labeled": "标注状态",
        "sort.score": "分数",
        "sort.date": "发布时间",
        "labeled.any": "不限",
        "labeled.no": "未标注",
        "labeled.yes": "已标注",
        # 列表
        "list.label": "岗位列表",
        "list.empty": "这个视图是空的",
        "list.empty_filtered": "没有符合条件的岗位",
        "list.empty_hint": "试试清除筛选，或去「全部」看看。",
        "list.prev": "← 上一页",
        "list.next": "下一页 →",
        "list.page": "第 {page} / {pages} 页",
        "list.count": "本页 {n} / {total}",
        "card.excluded": "已排除",
        "card.rule": "规则 {rule}",
        "card.score": "总分：越高越匹配",
        "age.tag": "挂出 {days} 天",
        "tag.raw": "原文 {text}",
        "tag.experience": "经验 {years}+ 年 {delta}",
        "tag.salary_year": "/年",
        "tag.salary_from_text": "（正文）",
        # 上次抓取
        "run.never": "尚未抓取",
        "run.at": "上次抓取 {stamp}",
        "run.ago": "上次抓取 {ago}",
        "run.stale": "　⚠ 定时任务可能已停",
        # 规则开关（最近一次成功 analyze 使用的 profile / 开关）
        "rule.title": "规则开关",
        "rule.used": "最近一次分析使用",
        "rule.unavailable": "旧分析未记录 profile",
        "rule.profile": "profile",
        "rule.source": "来源",
        "rule.disabled": "已关闭",
        "rule.explicit": "显式覆盖",
        "rule.none": "无",
        "rule.default_profile": "缺省（全部规则开启）",
        "rule.note": "软件规则开关，非法律资格判断",
        "ago.minutes": "{n} 分钟前",
        "ago.hours": "{n} 小时前",
        "ago.days": "{n} 天前",
        # 详情
        "detail.label": "岗位详情",
        "detail.placeholder": "← 从左侧选一条岗位，正文会显示在这里",
        "detail.back": "← 返回列表",
        "detail.open": "打开原文",
        "detail.posted": "发布 {date}",
        "detail.dupes": "另有 {n} 条重复（{sources}）",
        "detail.rule": "被规则排除：",
        "detail.matched": "命中：",
        "detail.step1": "先看资格线索",
        "detail.original": "原文摘录 · 不翻译",
        "detail.evidence_note": "这只是提取到的局部要求，不代表整份岗位已确认可投。",
        "detail.step2": "做标记",
        "detail.step3": "写备注",
        "detail.optional": "可选",
        "detail.decide": "判断与标注",
        "detail.jd": "岗位正文",
        "detail.jd_note": "原文",
        "detail.jd_empty": "（这份 JD 没有抓到正文）",
        "detail.skill_edit": "编辑技能",
        "detail.skill_head": "技能词表",
        "detail.skill_placeholder": "输入一个词：回车新增，或从候选选一个作为别名",
        "detail.skill_hint": "点候选 = 把该词设为已有技能的别名；回车 = 新增技能。改动会立即重算全库技能并刷新",
        "detail.note_placeholder": "备注…（点一下出候选，可滚动）",
        "detail.note_hint": "点候选即可追加；用「；」分隔多个标签，回车保存。",
        "help.button": "这三个标记有什么区别？",
        "help.eligibility": "按资格门槛判断你能不能投，例如公民 / PR、保密许可、签证。只记事实判断，不代表想不想投。",
        "help.interest": "不管能不能投，你想不想要这份工作。",
        "help.action": "实际做到哪一步：待投、已投或跳过。",
        "help.foot": "三个标记互相独立，比如「可投 + 不投」也是正常组合。再点一次已选中的按钮可以清除。列表卡片右下角的三个圆点按同样顺序显示这三项，空心表示还没标。",
        # 标注三轴
        "field.eligibility": "可投性",
        "field.interest": "兴趣",
        "field.action": "投递进度",
        "field.note": "备注",
        "value.eligibility.eligible": "可投",
        "value.eligibility.ineligible": "不可投",
        "value.eligibility.unsure": "待定",
        "value.interest.want": "想投",
        "value.interest.maybe": "也许",
        "value.interest.no": "不投",
        "value.action.saved": "待投",
        "value.action.applied": "已投",
        "value.action.skipped": "跳过",
        "dots.unset": "未标注",
        # 资格线索（render.ELIGIBILITY_CUES 的显示名；键是内部值）
        "cue.保密等级": "保密等级",
        "cue.保密审查": "保密审查",
        "cue.公民/PR": "公民/PR",
        "cue.工作权": "工作权",
        "cue.警察检查": "警察检查",
        "cue.原住民专属": "原住民专属",
        "cue.驾照": "驾照",
        # 设置页
        "set.fetch": "抓取与更新",
        "set.fetch_title": "当前抓取配置",
        "set.fetch_hint": "以下配置将在下一次更新时读取。修改配置不会自动重新处理已显示的岗位；下方 Profile 记录最近成功分析使用的规则。",
        "set.fetch_readonly": "此处仅展示配置。如需修改，请编辑启动面板所用的配置文件，再刷新此页核对。",
        "set.update_hint": "依次抓取岗位、补全详情、分析并生成报告。新结果在未打开岗位时自动载入；已打开的岗位与未保存备注会保留。",
        "set.fetch_queries": "关键词",
        "set.fetch_locations": "地区",
        "set.fetch_sources": "来源与抓取范围",
        "set.fetch_enabled": "已启用",
        "set.fetch_disabled": "未启用",
        "set.fetch_none": "未配置",
        "set.fetch_pages_per_query": "每个关键词页数",
        "set.fetch_daterange": "最近天数",
        "set.fetch_results_wanted": "每个关键词请求条数（上限）",
        "set.fetch_fetch_description": "抓取完整描述",
        "set.fetch_country_indeed": "国家",
        "set.fetch_yes": "是",
        "set.fetch_no": "否",
        "set.fetch_anytime": "不限时间",
        "set.fetch_changed": "配置与面板启动时不同；下一次更新会重新读取。",
        "js.update_title": "更新岗位",
        "js.update_refresh": "刷新查看结果",
        "js.update_checking": "正在检查更新状态…",
        "js.update_nojs": "启用 JavaScript 后可查看更新状态并发起更新。",
        "js.update_idle": "可以开始更新",
        "js.update_running": "正在更新 · {stage}",
        "js.update_starting": "正在启动更新…",
        "js.update_success": "更新完成。",
        "js.update_partial": "更新未完整完成，部分岗位可能已保存。可以重试。",
        "js.update_error": "更新未完成，部分数据可能已保存。可以重试。",
        "js.update_busy": "定时任务正在使用更新流程，请稍后重试。",
        "js.update_timeout": "更新已超时并停止，部分数据可能已保存。可以重试。",
        "js.update_interrupted": "上次更新被中断，部分数据可能已保存。可以重试。",
        "js.update_unavailable": "暂时无法确认更新状态；恢复连接后会自动重试。",
        "js.update_disabled": "此面板未启用岗位更新。",
        "js.update_demo_disabled": "演示环境仅浏览合成数据，不会抓取真实岗位。",
        "js.update_stage_fetch": "抓取岗位",
        "js.update_stage_details": "补全详情",
        "js.update_stage_analyze": "分析岗位",
        "js.update_stage_report": "生成报告",
        "js.update_stage_wait": "准备中",
        "js.update_counts": "发现 {seen} · 新增 {inserted} · 已有更新 {updated} · 详情补全 {details_fetched}",
        "js.update_started": "开始：{time}",
        "js.update_finished": "结束：{time}",
        "js.update_failed_sources": "未完成来源：{sources}",
        "js.update_config_invalid": "配置无效，请检查配置后重试。",
        "js.update_config_unavailable": "无法读取配置，请检查配置后重试。",
        "js.update_reload_required": "数据库或输出位置已更改。请按新配置重启面板后再更新。",
        "js.update_no_sources": "未启用抓取来源，请先检查配置。",
        "js.update_storage_unavailable": "无法保存更新状态，请检查本地存储后重试。",
        "js.update_config_failed": "暂时无法读取抓取配置，请刷新此页重试。",
        "set.sections": "设置分类",
        "set.skills": "技术栈",
        "set.display": "显示",
        "set.skills_title": "技术栈词表",
        "set.skills_hint": "技能用于筛选，不参与打分。点铅笔可编辑别名和展示名。你的修改单独保存，不会改动内置词表。",
        "set.add_placeholder": "新增技能，如 Splunk",
        "set.add": "新增",
        "set.filter_placeholder": "搜索技能或别名…",
        "set.legend": "颜色：",
        "set.legend_hint": "鼠标停在名称或别名上可看来源说明",
        "set.col_name": "技能",
        "set.col_alias": "别名",
        "set.col_hits": "命中",
        "set.col_source": "来源",
        "set.seed": "种子",
        "set.local": "本地",
        "set.tip_seed": "内置关键词：随项目提供，界面不会改动它。",
        "set.tip_local": "本地关键词：你在面板或命令行里添加的，单独保存。",
        "set.tip_mixed": "内置 + 本地：内置的条目，你又改过它的别名（新增或移除）。",
        "set.flag_ambiguous": "歧义词：需要同篇有其他技术词佐证",
        "set.flag_not": "带排除规则（not）",
        "set.edit": "编辑",
        "set.no_match": "没有匹配的技能",
        "set.empty": "词表是空的",
        "set.no_alias": "没有别名",
        "set.footnote": "技能名与别名同时用于提取、搜索和展示，不随界面语言翻译。",
        "set.edit_title": "编辑技能",
        "set.close": "关闭",
        "set.primary": "主要展示名",
        "set.not_yet": "功能暂未实现",
        "set.primary_now": "卡片和筛选里显示这个名字；匹配仍使用全部名称",
        "set.drop_here": "松手，设为主要展示名",
        "set.reset_to": "恢复为 {name}",
        "set.guide1": "按住下方任一名称",
        "set.guide2": "拖进上面的虚线框",
        "set.guide3": "松手即替换",
        "set.guide_note": "原展示名会回到下方列表，不会被删除。触屏或键盘：直接点一下名称也能设为展示名。",
        "set.primary_unsaved": "主要展示名有未保存的改动。放弃并关闭？",
        "set.others": "其他名称",
        "set.drag_tip": "可拖到上方设为主要展示名",
        "set.set_primary": "设为主要展示名",
        "set.remove_alias": "删除别名",
        "set.alias_placeholder": "新别名，回车保存",
        "set.alias_hint": "移除内置别名只记在你的本地修改里，不会改动内置词表。",
        "set.delete_skill": "删除技能（连同别名）",
        "set.confirm_delete": "确认删除",
        "set.done": "完成",
        "set.lang_title": "界面语言",
        "set.lang_desc": "只翻译按钮、筛选和提示等界面文字；岗位内容和你的备注不翻译。",
        "set.lang_auto": "跟随浏览器",
        "set.lang_auto_desc": "按浏览器语言，默认中文",
        "set.lang_zh_desc": "简体中文界面",
        "set.lang_en_desc": "英文界面",
        "set.theme_title": "外观",
        "set.theme_auto": "跟随系统",
        "set.theme_light": "浅色",
        "set.theme_dark": "深色",
        "set.profile_title": "分析规则",
        "set.profile_label": "Profile：{name}",
        "set.profile_used": "最近一次分析使用",
        "set.profile_citizen": "公民",
        "set.profile_permanent_resident": "永久居民",
        "set.profile_485": "485",
        "set.profile_whv": "WHV（打工度假）",
        "js.update_unknown": "结果未记录（旧版本运行）",
        "js.update_pending": "离开当前岗位后将加载新结果",
        "js.unsaved_leave": "有未保存更改。放弃并继续？",
        "js.update_trigger": "触发方式：{source}",
        "js.update_task": "任务 ID：{id}",
        "js.update_trigger_manual": "手动",
        "js.update_trigger_scheduled": "定时",
        "js.update_trigger_cli": "命令行",
        "js.update_trigger_unknown": "未记录",

        "set.profile_student_visa": "学生",
        "set.profile_custom": "自定义",
        "set.profile_default": "默认 / 全部规则开启",
        "set.profile_unrecorded": "未记录 / 重新分析后显示",
        "set.profile_unknown": "未知",
        "set.keep_title": "切换语言不会修改已保存的内容",
        "set.keep1": "岗位正文、公司名、地点与资格原文摘录",
        "set.keep2": "你的备注、标注与投递记录（自定义备注保持原样，默认标签按界面语言显示）",
        "set.keep3": "技能名称、别名与数据库里的枚举值",
        # 顶栏「显示」菜单（语言 + 外观），选项与顺序同设置页、手机抽屉
        "display.button": "显示",
        "display.label": "显示：语言与外观",
        "display.more": "同样的选项也在 设置 → 显示。",
        "set.theme_auto_desc": "按系统的深浅色设置",
        # 更新岗位：确认后才开始（会联网）
        "update.confirm_title": "现在更新岗位？",
        "update.confirm_body": "会联网抓取已启用的招聘网站，再补全详情、分析并生成报告，通常需要几分钟。期间可以继续浏览，已打开的岗位和未保存的备注都会保留。",
        "update.confirm_ok": "开始更新",
        "update.cancel": "取消",
        "update.details": "运行详情",
        # 状态行里的简短结果（完整说明在设置页与悬停提示）
        "run.state_partial": "部分完成",
        "run.state_error": "未完成",
        "run.state_timeout": "已超时",
        "run.state_interrupted": "被中断",
        "run.state_unknown": "结果未记录（旧版本运行）",
        # 卡片：薪资来源、技能、进度；详情：计分明细（加减分从卡片移到这里）
        "salary.tip_annualized": "≈ 表示由时薪或日薪折算成年薪",
        "salary.tip_text": "（正文）表示薪资是从岗位正文里找到的",
        "salary.tip_raw": "原文：{text}",
        "card.skills": "技能：{list}",
        "card.tier_score": "层级 {tier} · 总分 {score}：越高越匹配",
        "detail.why": "为什么是 {tier} · {score} 分",
        "detail.why_plain": "为什么是 {score} 分",
        "detail.why_hint": "计分明细，与报告同口径；加减分只在这里显示。",
        "detail.why_tier": "层级",
        "detail.why_empty": "没有加减分项。",
        # 设置：资格与规则
        "set.rules": "资格与规则",
        "set.rules_title": "资格与规则",
        "set.rules_hint": "选择与你身份相符的规则预设，它决定哪些岗位会被硬规则排除。这是软件规则，不是法律资格判断。保存只用于下一次分析，不会重算现在显示的结果。",
        # 前端脚本用到的反馈（window.__I18N__）
        "js.loading": "载入中…",
        "js.load_failed": "载入失败：",
        "js.label_failed": "标注失败: ",
        "js.labelled": "已标注",
        "js.unlabelled": "已取消",
        "js.miss_hint": "已标为不可投 — 若它未被规则排除，这就是漏杀",
        "js.note_saved": "备注已保存",
        "js.note_failed": "备注保存失败: ",
        "js.note_no_match": "无匹配候选 — 回车即保存为自定义标签",
        "js.note_no_more": "没有更多候选，直接输入即可",
        "js.note_count": "共 {n} 项 — 可滚动，或继续输入筛选",
        "js.skill_add": "+ 新增技能「{token}」",
        "js.skill_as_alias": "作为「{name}」的别名",
        "js.skill_empty": "输入一个词，回车即加入词表",
        "js.skill_saving": "正在保存…",
        "js.skill_added": "已加入技能：{token}",
        "js.skill_aliased": "「{token}」→「{name}」别名",
        "js.skill_recalc": "已保存，正在重算全库…",
        "js.skill_failed": "技能词表保存失败: ",
        "js.saved": "已保存",
        "js.deleted": "已删除",
        "js.save_failed": "保存失败: ",
        "js.dots_sep": "　",
        "js.colon": "：",
        "js.note_sep": "；",
        "js.note_gap": "",
    },
    "en": {
        "app.title": "AU Job Board",
        "settings.title": "Settings",
        "nav.views": "Views",
        "nav.menu": "Open menu",
        "nav.menu_close": "Close menu",
        "nav.settings": "Settings",
        "nav.settings_hint": "Rules, fetching, skills, display",
        "nav.back": "Back to board",
        "lang.current": "English",
        "lang.other": "中文",
        "lang.switch": "切换到中文界面",
        "theme.to_dark": "Switch to dark mode",
        "theme.to_light": "Switch to light mode",
        "view.recommend": "For you",
        "view.all": "All",
        "view.new": "New",
        "view.excluded": "Excluded",
        "view.labelled": "Labelled",
        "viewhint.recommend": "Unlabelled, best score first",
        "viewhint.all": "Everything, incl. excluded",
        "viewhint.new": "Latest fetch",
        "viewhint.excluded": "Grouped by rule",
        "viewhint.labelled": "Jobs you labelled",
        "viewdesc.recommend": "Jobs you haven’t labelled, highest score first. One low-score job in every 10 is mixed in for calibration. Listings older than 30 days are left out.",
        "viewdesc.all": "Every job after de-duplication, including ones excluded by rules (marked “Excluded”).",
        "viewdesc.new": "Jobs added by the most recent fetch, including excluded ones.",
        "viewdesc.excluded": "Jobs blocked by hard rules, grouped by rule. Look here for missed or wrong exclusions.",
        "viewdesc.labelled": "Jobs you’ve labelled, including excluded ones. Turn on “Priority only” for your apply queue.",
        "stat.labelled": "Labelled",
        "stat.saved": "To apply",
        "stat.applied": "Applied",
        "stat.miss": "Marked ineligible, not excluded",
        "stat.false_excl": "Excluded, marked eligible",
        "stat.batch": "In this batch",
        "stat.rules": "excluded",
        "search.placeholder": "Search title, company, location, notes, tags, description…",
        "search.label": "Search",
        "search.explain": "Search: <b>{query}</b> → {terms}{all}, {total} results",
        "search.all_match": " (all must match)",
        "term.skill": "skill “{label}”",
        "term.prefix": "prefix “{label}”",
        "term.word": "whole word “{label}”",
        "filter.more": "More filters",
        "filter.button": "Filters",
        "filter.done": "Done",
        "filter.clear_hidden": "Clear these filters",
        "filter.clear_all": "Clear all filters",
        "filter.active": "Active:",
        "filter.remove": "Remove filter",
        "filter.group.label": "Labels",
        "filter.group.label_hint": "by your judgement",
        "filter.group.job": "Job details",
        "filter.group.job_hint": "by the listing",
        "filter.any": "Any",
        "filter.none": "Not set",
        "filter.salary": "Salary stated only",
        "filter.salary_chip": "Has salary",
        "filter.fresh": "Last 30 days only",
        "filter.priority": "Priority only",
        "filter.skill": "Skills",
        "filter.skill_hint": "match any",
        "filter.tier": "Tier",
        "filter.sort": "Sort",
        "filter.labeled": "Label status",
        "sort.score": "Score",
        "sort.date": "Date posted",
        "labeled.any": "Any",
        "labeled.no": "Unlabelled",
        "labeled.yes": "Labelled",
        "list.label": "Job list",
        "list.empty": "This view is empty",
        "list.empty_filtered": "No jobs match these filters",
        "list.empty_hint": "Try clearing filters, or check All.",
        "list.prev": "← Previous",
        "list.next": "Next →",
        "list.page": "Page {page} of {pages}",
        "list.count": "{n} of {total} on this page",
        "card.excluded": "Excluded",
        "card.rule": "Rule {rule}",
        "card.score": "Total score: higher is a better match",
        "age.tag": "Listed {days} days",
        "tag.raw": "Posted as {text}",
        "tag.experience": "Experience {years}+ yrs {delta}",
        "tag.salary_year": "/yr",
        "tag.salary_from_text": " (from description)",
        "run.never": "Not fetched yet",
        "run.at": "Last fetched {stamp}",
        "run.ago": "Last fetched {ago}",
        "run.stale": " ⚠ scheduled job may have stopped",
        # Rule switches (profile / switches used by the last successful analyze)
        "rule.title": "Rule switches",
        "rule.used": "Used by the last analyze",
        "rule.unavailable": "Old analyze did not record a profile",
        "rule.profile": "profile",
        "rule.source": "source",
        "rule.disabled": "disabled",
        "rule.explicit": "explicit",
        "rule.none": "none",
        "rule.default_profile": "default (all rules on)",
        "rule.note": "Software rule switch, not a legal eligibility determination",
        "ago.minutes": "{n} min ago",
        "ago.hours": "{n} h ago",
        "ago.days": "{n} days ago",
        "detail.label": "Job details",
        "detail.placeholder": "← Pick a job on the left to read it here",
        "detail.back": "← Back to list",
        "detail.open": "Open listing",
        "detail.posted": "Posted {date}",
        "detail.dupes": "{n} duplicates ({sources})",
        "detail.rule": "Excluded by rule: ",
        "detail.matched": "Matched: ",
        "detail.step1": "Check the eligibility cue",
        "detail.original": "Original excerpt · not translated",
        "detail.evidence_note": "This is one extracted requirement. It does not confirm you are eligible for the whole role.",
        "detail.step2": "Label it",
        "detail.step3": "Add a note",
        "detail.optional": "optional",
        "detail.decide": "Review and label",
        "detail.jd": "Job description",
        "detail.jd_note": "original text",
        "detail.jd_empty": "(No description was captured for this posting)",
        "detail.skill_edit": "Edit skills",
        "detail.skill_head": "Skill vocabulary",
        "detail.skill_placeholder": "Type a term: Enter to add, or pick a skill to add it as an alias",
        "detail.skill_hint": "Pick a skill = add the term as its alias; Enter = add a new skill. Skill tags are recomputed right away",
        "detail.note_placeholder": "Notes… (click for suggestions, scrollable)",
        "detail.note_hint": "Pick a suggestion to add it. Separate tags with a semicolon (;) and press Enter to save.",
        "help.button": "How are these three labels different?",
        "help.eligibility": "Whether the role’s requirements let you apply, such as citizenship / PR, clearance or visa. A factual call, not whether you want it.",
        "help.interest": "Whether you want this job, regardless of eligibility.",
        "help.action": "Where you are with it: saved, applied or skipped.",
        "help.foot": "The three labels are independent: “Eligible + No” is a normal combination. Click a selected button again to clear it. The three dots on each card show these labels in the same order; hollow means not set.",
        "field.eligibility": "Eligibility",
        "field.interest": "Interest",
        "field.action": "Progress",
        "field.note": "Notes",
        "value.eligibility.eligible": "Eligible",
        "value.eligibility.ineligible": "Ineligible",
        "value.eligibility.unsure": "Unsure",
        "value.interest.want": "Want",
        "value.interest.maybe": "Maybe",
        "value.interest.no": "No",
        "value.action.saved": "Saved",
        "value.action.applied": "Applied",
        "value.action.skipped": "Skipped",
        "dots.unset": "not set",
        "cue.保密等级": "Clearance level",
        "cue.保密审查": "Security clearance",
        "cue.公民/PR": "Citizen / PR",
        "cue.工作权": "Work rights",
        "cue.警察检查": "Police check",
        "cue.原住民专属": "Identified position",
        "cue.驾照": "Driver’s licence",
        "set.fetch": "Fetching & updates",
        "set.fetch_title": "Current fetch configuration",
        "set.fetch_hint": "These settings are read for the next update. Configuration changes do not automatically reprocess displayed jobs; the Profile below records the last successful analysis.",
        "set.fetch_readonly": "This view is read-only. Edit the configuration file used to start the panel, then refresh this page to check it.",
        "set.update_hint": "Fetch jobs, fill descriptions, analyze and report in the background. New results load when no job is open; open jobs and unsaved notes are protected.",
        "set.fetch_queries": "Search terms",
        "set.fetch_locations": "Locations",
        "set.fetch_sources": "Sources & fetch scope",
        "set.fetch_enabled": "Enabled",
        "set.fetch_disabled": "Disabled",
        "set.fetch_none": "Not configured",
        "set.fetch_pages_per_query": "Pages per term",
        "set.fetch_daterange": "Posted within days",
        "set.fetch_results_wanted": "Requested results per term (limit)",
        "set.fetch_fetch_description": "Fetch full descriptions",
        "set.fetch_country_indeed": "Country",
        "set.fetch_yes": "Yes",
        "set.fetch_no": "No",
        "set.fetch_anytime": "Any time",
        "set.fetch_changed": "Configuration has changed since the panel started; the next update will read it again.",
        "js.update_title": "Update jobs",
        "js.update_refresh": "Refresh results",
        "js.update_checking": "Checking update status…",
        "js.update_nojs": "Enable JavaScript to check update status and start an update.",
        "js.update_idle": "Ready to update",
        "js.update_running": "Updating · {stage}",
        "js.update_starting": "Starting update…",
        "js.update_success": "Update complete.",
        "js.update_partial": "Update partly complete. Some jobs may have been saved. You can retry.",
        "js.update_error": "Update did not complete. Some data may have been saved. You can retry.",
        "js.update_busy": "A scheduled task is using the update pipeline. Try again shortly.",
        "js.update_timeout": "Update timed out and stopped. Some data may have been saved. You can retry.",
        "js.update_interrupted": "The previous update was interrupted. Some data may have been saved. You can retry.",
        "js.update_unavailable": "Update status is temporarily unavailable. It will retry when the connection returns.",
        "js.update_disabled": "Job updates are not available in this panel.",
        "js.update_demo_disabled": "This demo uses synthetic data and does not fetch real jobs.",
        "js.update_stage_fetch": "Fetching jobs",
        "js.update_stage_details": "Filling in descriptions",
        "js.update_stage_analyze": "Analyzing jobs",
        "js.update_stage_report": "Generating reports",
        "js.update_stage_wait": "Preparing",
        "js.update_counts": "Found {seen} · Added {inserted} · Updated {updated} · Descriptions {details_fetched}",
        "js.update_started": "Started: {time}",
        "js.update_finished": "Finished: {time}",
        "js.update_failed_sources": "Incomplete sources: {sources}",
        "js.update_config_invalid": "Configuration is invalid. Check it and try again.",
        "js.update_config_unavailable": "Configuration could not be read. Check it and try again.",
        "js.update_reload_required": "The database or output location has changed. Restart the panel with the new configuration before updating.",
        "js.update_no_sources": "No fetch sources are enabled. Check the configuration first.",
        "js.update_storage_unavailable": "Update state could not be saved. Check local storage and try again.",
        "js.update_config_failed": "Fetch configuration is temporarily unavailable. Refresh this page to try again.",
        "set.sections": "Settings sections",
        "set.skills": "Skills",
        "set.display": "Display",
        "set.skills_title": "Skill vocabulary",
        "set.skills_hint": "Skills are a filter, not part of the score. Use the pencil to edit aliases and the display name. Your changes are saved separately and never alter the built-in list.",
        "set.add_placeholder": "New skill, e.g. Splunk",
        "set.add": "Add",
        "set.filter_placeholder": "Search skills or aliases…",
        "set.legend": "Colours:",
        "set.legend_hint": "Hover a name or alias to see where it comes from",
        "set.col_name": "Skill",
        "set.col_alias": "Aliases",
        "set.col_hits": "Hits",
        "set.col_source": "Source",
        "set.seed": "Seed",
        "set.local": "Local",
        "set.tip_seed": "Built-in term: ships with the project; the UI never edits it.",
        "set.tip_local": "Local term: added by you in the panel or command line, saved separately.",
        "set.tip_mixed": "Built-in + local: a built-in entry whose aliases you changed (added or removed).",
        "set.flag_ambiguous": "Ambiguous: needs another skill term in the same listing",
        "set.flag_not": "Has exclusion patterns (not)",
        "set.edit": "Edit",
        "set.no_match": "No matching skills",
        "set.empty": "The vocabulary is empty",
        "set.no_alias": "No aliases",
        "set.footnote": "Skill names and aliases drive extraction, search and display, so they are not translated with the UI.",
        "set.edit_title": "Edit skill",
        "set.close": "Close",
        "set.primary": "Display name",
        "set.not_yet": "Not implemented yet",
        "set.primary_now": "Shown on cards and filters; matching still uses every name",
        "set.drop_here": "Drop to make this the display name",
        "set.reset_to": "Reset to {name}",
        "set.guide1": "Press and hold a name below",
        "set.guide2": "Drag it into the dashed box",
        "set.guide3": "Release to replace",
        "set.guide_note": "The previous display name moves back to the list below; nothing is deleted. On touch or keyboard, tap a name to set it.",
        "set.primary_unsaved": "The display name has unsaved changes. Discard and close?",
        "set.others": "Other names",
        "set.drag_tip": "Drag up to make it the display name",
        "set.set_primary": "Set as display name",
        "set.remove_alias": "Remove alias",
        "set.alias_placeholder": "New alias, Enter to save",
        "set.alias_hint": "Removing a built-in alias is recorded only in your local changes; the built-in list is not edited.",
        "set.delete_skill": "Delete skill and aliases",
        "set.confirm_delete": "Confirm delete",
        "set.done": "Done",
        "set.lang_title": "Interface language",
        "set.lang_desc": "Translates interface text such as buttons, filters and hints; job content and your notes are not translated.",
        "set.lang_auto": "Match browser",
        "set.lang_auto_desc": "Uses the browser language, Chinese by default",
        "set.lang_zh_desc": "Simplified Chinese UI",
        "set.lang_en_desc": "English UI",
        "set.theme_title": "Appearance",
        "set.theme_auto": "Match system",
        "set.theme_light": "Light",
        "set.theme_dark": "Dark",
        "set.profile_title": "Analysis rules",
        "set.profile_label": "Profile: {name}",
        "set.profile_used": "Used by the last analyze",
        "set.profile_citizen": "Citizen",
        "set.profile_permanent_resident": "PR",
        "set.profile_485": "485",
        "set.profile_whv": "Working Holiday (WHV)",
        "js.update_unknown": "Outcome not recorded (older version run)",
        "js.update_pending": "New results will load when you leave this job",
        "js.unsaved_leave": "Unsaved changes. Discard and continue?",
        "js.update_trigger": "Started by: {source}",
        "js.update_task": "Task ID: {id}",
        "js.update_trigger_manual": "Manual",
        "js.update_trigger_scheduled": "Scheduled",
        "js.update_trigger_cli": "Command line",
        "js.update_trigger_unknown": "Not recorded",

        "set.profile_student_visa": "Student",
        "set.profile_custom": "Custom",
        "set.profile_default": "Default / all rules on",
        "set.profile_unrecorded": "Not recorded / shown after re-analysis",
        "set.profile_unknown": "Unknown",
        "set.keep_title": "Changing language does not modify your saved data",
        "set.keep1": "Job descriptions, company names, locations and eligibility excerpts",
        "set.keep2": "Your notes, labels and application history (custom notes stay as written; default tags display in the UI language)",
        "set.keep3": "Skill names, aliases and stored enum values",
        "display.button": "Display",
        "display.label": "Display: language and appearance",
        "display.more": "The same options are in Settings → Display.",
        "set.theme_auto_desc": "Follows your system light/dark setting",
        "update.confirm_title": "Update jobs now?",
        "update.confirm_body": "This goes online to fetch from the enabled job sites, then fills in descriptions, analyzes and writes reports. It usually takes a few minutes. You can keep browsing; the open job and unsaved notes are kept.",
        "update.confirm_ok": "Start update",
        "update.cancel": "Cancel",
        "update.details": "Run details",
        "run.state_partial": "partly complete",
        "run.state_error": "did not complete",
        "run.state_timeout": "timed out",
        "run.state_interrupted": "interrupted",
        "run.state_unknown": "outcome not recorded (older version run)",
        "salary.tip_annualized": "≈ means converted from an hourly or daily rate to a yearly amount",
        "salary.tip_text": "(from description) means the salary was found in the job description",
        "salary.tip_raw": "Posted as: {text}",
        "card.skills": "Skills: {list}",
        "card.tier_score": "Tier {tier} · total score {score}: higher is a better match",
        "detail.why": "Why {tier} · {score} points",
        "detail.why_plain": "Why {score} points",
        "detail.why_hint": "Score breakdown, same as the report; score adjustments are shown only here.",
        "detail.why_tier": "Tier",
        "detail.why_empty": "No score adjustments.",
        "set.rules": "Eligibility & rules",
        "set.rules_title": "Eligibility & rules",
        "set.rules_hint": "Pick the preset that matches your status; it decides which jobs hard rules exclude. These are software rules, not a legal eligibility determination. Saving applies to the next analysis and does not recompute the results shown now.",
        "js.loading": "Loading…",
        "js.load_failed": "Couldn’t load: ",
        "js.label_failed": "Couldn’t save label: ",
        "js.labelled": "Saved",
        "js.unlabelled": "Cleared",
        "js.miss_hint": "Marked ineligible — if rules didn’t exclude it, that’s a miss",
        "js.note_saved": "Note saved",
        "js.note_failed": "Couldn’t save note: ",
        "js.note_no_match": "No suggestions — press Enter to save as a custom tag",
        "js.note_no_more": "No more suggestions; just type",
        "js.note_count": "{n} items — scroll, or keep typing to filter",
        "js.skill_add": "+ Add skill “{token}”",
        "js.skill_as_alias": "As an alias of “{name}”",
        "js.skill_empty": "Type a term and press Enter to add it",
        "js.skill_saving": "Saving…",
        "js.skill_added": "Added skill: {token}",
        "js.skill_aliased": "“{token}” → alias of “{name}”",
        "js.skill_recalc": "Saved, recomputing…",
        "js.skill_failed": "Couldn’t save vocabulary: ",
        "js.saved": "Saved",
        "js.deleted": "Deleted",
        "js.save_failed": "Couldn’t save: ",
        "js.dots_sep": " · ",
        "js.colon": ": ",
        "js.note_sep": ";",
        "js.note_gap": " ",
    },
}


def norm_lang(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    if value.startswith("zh"):
        return "zh"
    if value.startswith("en"):
        return "en"
    return None


def parse_cookies(header: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" in part:
            key, _, value = part.strip().partition("=")
            out[key.strip()] = value.strip()
    return out


def resolve_lang(cookie_header: str | None = None, accept_language: str | None = None) -> str:
    """cookie > Accept-Language（按 q 值取第一个认得的）> 中文。"""
    chosen = norm_lang(parse_cookies(cookie_header).get(LANG_COOKIE))
    if chosen:
        return chosen
    ranked = []
    for i, item in enumerate((accept_language or "").split(",")):
        tag, _, params = item.strip().partition(";")
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 0.0
        ranked.append((-q, i, tag))
    for _q, _i, tag in sorted(ranked):
        if (lang := norm_lang(tag)):
            return lang
    return DEFAULT_LANG


def resolve_theme(cookie_header: str | None = None) -> str | None:
    """明确选过浅色/深色才返回；None = 跟随系统。"""
    value = parse_cookies(cookie_header).get(THEME_COOKIE)
    return value if value in THEMES else None


def lang_pref(cookie_header: str | None = None) -> str:
    """设置页显示用：用户明确选过的语言，没选过是 auto。"""
    return norm_lang(parse_cookies(cookie_header).get(LANG_COOKIE)) or "auto"


def t(lang: str, key: str, **kwargs) -> str:
    table = STRINGS.get(lang) or STRINGS[DEFAULT_LANG]
    text = table.get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANG].get(key, key)
    return text.format(**kwargs) if kwargs else text


def value_label(lang: str, field: str, value: str | None) -> str:
    """标注枚举的显示名。存储值不变，未知值原样显示。"""
    if not value:
        return ""
    key = f"value.{field}.{value}"
    return t(lang, key) if key in STRINGS[DEFAULT_LANG] else str(value)


def cue_label(lang: str, cue: str | None) -> str:
    """资格线索的显示名。cue 是 render.py 的内部值，认不得就原样显示。"""
    if not cue:
        return ""
    key = f"cue.{cue}"
    return t(lang, key) if key in STRINGS[DEFAULT_LANG] else str(cue)


# 备注分隔符。存储契约固定为全角「；」（jobs/labels.py NOTE_SEP）；面板只在
# **显示边界**按当前语言替换：中文「；」，英文「;」。不改存储、不做格式清洗。
NOTE_SEP_STORE = "；"

# 默认备注标签的英文显示名。canonical 值在 labels.NOTE_TAG_DEFAULTS；这里只做
# 显示映射，是 Python 与前端共用的**唯一数据来源**（经 __NOTE_TAG_LABELS__ 注入）。
NOTE_TAG_EN = {
    "搬迁": "Relocation",
    "地区偏远": "Remote location",
    "通勤远": "Long commute",
    "描述模糊": "Unclear description",
    "技术栈模糊": "Unclear tech stack",
    "技术栈不匹配": "Tech stack mismatch",
    "信息量低": "Limited information",
    "中介广告": "Agency listing",
    "非IT岗位": "Non-IT role",
    "本质IT Support（T2）": "Primarily IT Support (T2)",
    "资历略高": "Slightly above experience level",
    "经验要求偏高": "High experience requirement",
    "优先投递": "Prioritize",
    "之前已投": "Previously applied",
    "重复挂出": "Reposted listing",
    "需驾照": "Driver’s licence required",
    "需保密审查": "Security clearance required",
    "需公民或PR": "Citizenship or PR required",
    "时间冲突": "Schedule conflict",
    "资格句误判": "Eligibility requirement misclassified",
    "大厂": "Large company",
    "技术栈匹配": "Tech stack match",
}


def note_sep(lang: str) -> str:
    """当前语言的备注显示分隔符。"""
    return ";" if lang == "en" else NOTE_SEP_STORE


def note_gap(lang: str) -> str:
    """相邻完整标签之间、分隔符后的显示间隔：英文一个空格，中文无。

    只影响显示：结尾的分隔符后不补空格，已有空白不重复叠加，不产生空标签；
    存储与保存仍是 canonical「标签；标签；」。
    """
    return STRINGS[lang]["js.note_gap"] if lang in STRINGS else ""


def note_tag_display(lang: str, tag: str | None) -> str:
    """默认标签的显示名：中文原值、英文译名，认不得的自定义内容原样。"""
    if not tag:
        return tag or ""
    return NOTE_TAG_EN.get(tag, tag) if lang == "en" else tag


def note_tag_labels(lang: str) -> dict[str, str]:
    """注入前端的 canonical -> 当前语言显示名映射（只含默认标签）。"""
    return dict(NOTE_TAG_EN) if lang == "en" else {}


def display_note(lang: str, value: str | None) -> str:
    """把存储的备注转成当前语言的显示形态。

    **只动完整标签与分隔符**：按「；/;」切出的完整片段若是默认 canonical，换成
    当前语言显示名；其余片段与空白原样保留。不做全文/子串替换，不 trim、不折叠、
    不补尾 —— 真正的格式化只在用户显式保存时（jobs.labels.normalize_note）。
    """
    if not value:
        return ""
    sep = note_sep(lang)
    parts = re.split(r"([；;])", str(value))
    for i in range(0, len(parts), 2):
        seg = parts[i]
        tag = seg.strip()
        if not tag:
            continue
        display = note_tag_display(lang, tag)
        if display != tag and tag in seg:
            parts[i] = seg.replace(tag, display, 1)
    gap = note_gap(lang)
    for i in range(1, len(parts), 2):
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        parts[i] = sep + (gap if gap and nxt and not nxt[0].isspace() else "")
    return "".join(parts)


def js_strings(lang: str) -> dict[str, str]:
    """前端脚本用的那部分文案（去掉 js. 前缀），注入为 window.__I18N__。"""
    keys = [k for k in STRINGS[DEFAULT_LANG] if k.startswith(("js.", "set.", "field.", "value.", "dots.", "theme.", "filter.", "lang.", "run.", "ago."))]
    return {k: t(lang, k) for k in keys}
