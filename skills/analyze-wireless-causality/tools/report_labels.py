"""Localized report labels; prose is authored in the ledger language."""
EN = {
 'title':'Wireless performance investigation', 'analysis_status':'Execution status', 'scope':'Scope',
 'measurement_contract':'Measurement contract', 'phenomena':'Observed phenomena', 'findings':'Mechanisms and unresolved candidates',
 'calculation':'Calculation and selection', 'status':'Evidence status', 'priority_reason':'Priority rationale',
 'mechanism':'Mechanism', 'prediction':'Expected observation', 'strongest_alternative':'Strongest alternative explanation',
 'support':'Support', 'counterevidence':'Counterevidence', 'limitations':'Limitations', 'next_test':'Next discriminating check',
 'explains':'Explains phenomena', 'validation':'Validation', 'evidence':'Evidence records', 'reproduce':'Reproduction',
 'assessment':'Completion and answer assessment', 'numerical_claims':'Numerical claim checks', 'claim_type':'Type of claim',
 'priority_note':'Priority expresses investigation importance, not probability of causation.',
 'verification_note':'Integrity, location and arithmetic checks do not certify meaning, population selection or causal truth.',
 'claim_review':'Manual review of claim mapping', 'provenance':'Version, configuration and execution provenance',
 'execution':'Execution', 'data_capability':'Data capability', 'question_answer':'Question answered', 'delivery_quality':'Delivery quality',
 'delivery_checks':'Delivery checks', 'design':'Design', 'independent_replication':'Independent replication',
 'reviewer_assessment':'Reviewer assessment', 'result_path':'Result artifact', 'identification_scope':'Identification scope',
 'computed':'Recomputed', 'asserted':'Asserted', 'unit':'Unit', 'tolerance':'Tolerance', 'supports':'Supports', 'ledger':'Evidence ledger'
}
ZH = dict(zip(EN, [
 '无线性能调查','执行状态','范围','测量定义','观察到的现象','机制与未解决候选',
 '计算与选择规则','证据状态','优先级理由','机制','预期观察','最强替代解释',
 '支持证据','反证','限制','下一项区分检查','解释的现象','验证','证据记录','复现',
 '完成度与回答程度','数值主张核验','主张类型',
 '优先级表示调查重要程度，不代表因果概率。',
 '完整性、位置与算术核验不证明语义、样本选择或因果真实性。',
 '主张映射人工审查','版本、配置与执行来源','执行完成度','数据能力','问题回答程度','交付质量',
 '交付检查','设计','独立重复','审查者评估','结果文件','识别范围',
 '重算值','声明值','单位','容差','支持内容','证据账本'
]))

EXTRA_EN = {
 'full_audit': 'Complete machine-readable audit', 'version': 'Version', 'runtime': 'Runtime',
 'legacy_numeric': 'Legacy v2 ledgers do not include v3 numerical verification.',
 'summary': 'Executive summary', 'summary_empty': 'No summary items were selected; see the observations and scope below.',
 'contents': 'Contents', 'appendix': 'Audit appendix', 'figure': 'Figure', 'table': 'Table',
 'continued': 'continued', 'section': 'Section', 'detail': 'Detail', 'dimension': 'Dimension',
 'recorded_assessment': 'Assessments recorded in the ledger. Layout review for this export is recorded separately against its file hash.',
 'scope_limit': 'Scope and limits', 'no_items': 'No items are available in this section.',
 'render_provenance': 'Presentation provenance', 'audit_link': 'Audit detail',
 'display_note': 'Displayed table values are rounded for readability; exact values and tolerances are retained in the audit appendix.',
 'status_observed': 'Observed', 'status_candidate': 'Candidate', 'status_supported_candidate': 'Supported candidate',
 'status_validated_mechanism': 'Validated within stated scope', 'status_unresolved': 'Unresolved', 'status_refuted': 'Refuted',
 'status_completed': 'Completed', 'status_partial': 'Partial', 'status_blocked': 'Blocked',
 'status_sufficient': 'Sufficient', 'status_limited': 'Limited', 'status_unsupported': 'Unsupported',
 'status_answered': 'Answered', 'status_unanswered': 'Unanswered', 'status_passed': 'Passed',
 'status_failed': 'Failed', 'status_not_checked': 'Not checked', 'status_not_applicable': 'Not applicable',
 'status_association': 'Association', 'status_incremental_prediction': 'Incremental prediction',
 'status_mechanism_candidate': 'Mechanism candidate', 'status_intervention_effect': 'Intervention effect'
}
EXTRA_ZH = {
 'full_audit': '完整机器可读审计记录', 'version': '版本', 'runtime': '运行环境',
 'legacy_numeric': '旧版 v2 账本未执行 v3 数值核验。',
 'summary': '执行摘要', 'summary_empty': '未选择摘要条目，请结合下方现象与范围阅读。',
 'contents': '阅读导航', 'appendix': '审计附录', 'figure': '图', 'table': '表', 'continued': '续表',
 'section': '章节', 'detail': '说明', 'dimension': '维度',
 'recorded_assessment': '以下为证据账本记录的评估；本次导出的版式检查另行记录，并关联导出文件哈希。',
 'scope_limit': '适用范围与限制', 'no_items': '本节没有可报告的条目。',
 'render_provenance': '报告渲染来源', 'audit_link': '审计明细',
 'display_note': '表中数值按显示精度舍入；精确值与容差保留在审计附录中。',
 'status_observed': '已观察', 'status_candidate': '机制候选', 'status_supported_candidate': '有证据支持的候选',
 'status_validated_mechanism': '已在声明范围内验证', 'status_unresolved': '尚未解决', 'status_refuted': '已被反证',
 'status_completed': '已完成', 'status_partial': '部分完成', 'status_blocked': '受阻',
 'status_sufficient': '充分', 'status_limited': '有限', 'status_unsupported': '不支持',
 'status_answered': '已回答', 'status_unanswered': '未回答', 'status_passed': '通过',
 'status_failed': '失败', 'status_not_checked': '尚未检查', 'status_not_applicable': '不适用',
 'status_association': '关联', 'status_incremental_prediction': '增量预测',
 'status_mechanism_candidate': '机制候选', 'status_intervention_effect': '干预效果'
}
EN.update(EXTRA_EN)
ZH.update(EXTRA_ZH)


def labels(report, presentation=None):
    language = report.get('language', 'en')
    if presentation is not None and 'labels' in presentation:
        if presentation.get('language') != language or not isinstance(presentation['labels'], dict) or not set(EN) <= presentation['labels'].keys():
            raise ValueError('Presentation must match ledger language and provide every label; see report_labels.EN')
        result = presentation['labels']
    elif language in {'en', 'en-US', 'English'}:
        result = EN
    elif language in {'zh', 'zh-CN', 'Chinese', '中文'}:
        result = ZH
    else:
        raise ValueError('Supply a presentation label mapping for this language, or export the JSON model')
    if any(not isinstance(v, str) or not v.strip() for v in result.values()):
        raise ValueError('Presentation labels must be nonempty strings')
    return result
