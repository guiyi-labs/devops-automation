"""E4 巡检规则引擎：对 HostFacts 应用规则，产出 healthy/warning/critical/unknown。

规则模型（与 inspection_rule 表一致）：
- metric: 磁盘高水位 disk_used_pct / inode 高水位 inode_used_pct / 内存 memory_used_pct /
  swap 异常 swap_used_pct / load 持续过高 load_5 / 关键服务停止 service_stopped /
  端口未监听 port_not_listening
- operator: gt / lt / eq / ne / contains / not_contains
- threshold: "90"（百分比）、"3.5"（load）、"nginx"（服务名）、"8080"（端口）

整体判定：缺数据（无法采集或未知指标）固定 unknown，不误判为健康；
任何 critical 规则命中 → critical；否则任何 warning → warning；全部通过 → healthy。
"""
import json
from dataclasses import dataclass, field
from typing import Any


class STATUS:
    HEALTHY = 'healthy'
    WARNING = 'warning'
    CRITICAL = 'critical'
    UNKNOWN = 'unknown'
    ORDER = {UNKNOWN: 0, HEALTHY: 1, WARNING: 2, CRITICAL: 3}


@dataclass
class RuleResult:
    rule_id: int
    name: str
    metric: str
    status: str
    detail: str = ''


@dataclass
class Assessment:
    overall: str = STATUS.UNKNOWN
    results: list[RuleResult] = field(default_factory=list)


# ---------------- 取数（从 facts dict 提取规则所需值） ----------------

def _metric_value(facts: dict, metric: str) -> Any:
    """返回规则的待比较值；无法提取时返回 None（视为缺数据 → unknown）。"""
    if metric == 'disk_used_pct':
        disks = facts.get('disks') or []
        return max((d.get('used_pct') for d in disks if d.get('used_pct') is not None), default=None)
    if metric == 'inode_used_pct':
        disks = facts.get('disks') or []
        return max((d.get('inode_pct') for d in disks if d.get('inode_pct') is not None), default=None)
    if metric == 'memory_used_pct':
        return facts.get('memory_used_pct')
    if metric == 'swap_used_pct':
        return facts.get('swap_used_pct')
    if metric == 'load_5':
        return facts.get('load_5')
    if metric == 'service_stopped':
        return facts.get('active_services') or []
    if metric == 'port_not_listening':
        return facts.get('listening_ports') or []
    return None


def _compare(value: Any, operator: str, threshold: str) -> bool:
    """比较 value 与阈值。数字比较尽量数值化，容器用包含关系。"""
    if operator in ('gt', 'lt', 'eq', 'ne'):
        try:
            lhs, rhs = float(value), float(threshold)
        except (TypeError, ValueError):
            return False
        return {'gt': lhs > rhs, 'lt': lhs < rhs, 'eq': lhs == rhs,
                'ne': lhs != rhs}[operator]
    if operator in ('contains', 'not_contains'):
        value = value or []
        match = any(str(v) == threshold.strip() for v in value)
        return not match if operator == 'not_contains' else match
    return False


def evaluate(facts: dict, rules: list[dict]) -> Assessment:
    """对一条 facts 应用一组规则（dict 形式，来自 inspection_rule 行）。"""
    assessment = Assessment()
    if facts.get('unavailable_reason'):
        assessment.overall = STATUS.UNKNOWN
        assessment.results.append(RuleResult(
            rule_id=0, name='采集不可用', metric='collect',
            status=STATUS.UNKNOWN,
            detail=facts.get('unavailable_reason') or '无法采集主机事实',
        ))
        return assessment

    worst = STATUS.HEALTHY
    for rule in rules:
        if not rule.get('enabled', True):
            continue
        value = _metric_value(facts, rule['metric'])
        if value is None:
            status = STATUS.UNKNOWN
            detail = f'指标 {rule["metric"]} 无数据'
        elif _compare(value, rule['operator'], rule['threshold']):
            status = rule.get('severity', 'warning')
            detail = f'{rule["metric"]}={value} 触发({rule["operator"]} {rule["threshold"]})'
        else:
            status = STATUS.HEALTHY
            detail = f'{rule["metric"]}={value} 正常'
        assessment.results.append(RuleResult(
            rule_id=rule.get('id', 0), name=rule.get('name', rule['metric']),
            metric=rule['metric'], status=status, detail=detail,
        ))
        if STATUS.ORDER[status] > STATUS.ORDER[worst]:
            worst = status

    if worst == STATUS.HEALTHY and not assessment.results:
        worst = STATUS.UNKNOWN  # 一条规则都没有 → unknown
    assessment.overall = worst
    return assessment


def default_rules() -> list[dict]:
    """内置默认规则（种子用，对应实施方案 E4 巡检规则清单）。"""
    return [
        {'name': '磁盘高水位', 'description': '任一磁盘使用率超过 90%',
         'metric': 'disk_used_pct', 'operator': 'gt', 'threshold': '90', 'severity': 'warning'},
        {'name': '磁盘严重', 'description': '任一磁盘使用率超过 95%',
         'metric': 'disk_used_pct', 'operator': 'gt', 'threshold': '95', 'severity': 'critical'},
        {'name': 'inode 高水位', 'description': '任一磁盘 inode 使用率超过 90%',
         'metric': 'inode_used_pct', 'operator': 'gt', 'threshold': '90', 'severity': 'warning'},
        {'name': '内存压力', 'description': '内存使用率超过 90%',
         'metric': 'memory_used_pct', 'operator': 'gt', 'threshold': '90', 'severity': 'warning'},
        {'name': 'swap 异常', 'description': 'swap 使用率超过 50%',
         'metric': 'swap_used_pct', 'operator': 'gt', 'threshold': '50', 'severity': 'warning'},
        {'name': '负载持续过高', 'description': '5 分钟负载超过 4（按主机核数可调）',
         'metric': 'load_5', 'operator': 'gt', 'threshold': '4', 'severity': 'warning'},
        {'name': '关键服务停止', 'description': '指定服务名不在运行列表（配置 threshold=服务名）',
         'metric': 'service_stopped', 'operator': 'not_contains', 'threshold': 'nginx', 'severity': 'critical'},
        {'name': '端口未监听', 'description': '指定端口未监听（配置 threshold=端口；默认监视 SSH 22）',
         'metric': 'port_not_listening', 'operator': 'not_contains', 'threshold': '22', 'severity': 'warning'},
    ]


def serialize_results(assessment: Assessment) -> str:
    return json.dumps(
        [{'rule': r.name, 'metric': r.metric, 'status': r.status, 'detail': r.detail}
         for r in assessment.results],
        ensure_ascii=False,
    )