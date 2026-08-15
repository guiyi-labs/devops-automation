"""E3 受控批量运维：固定操作目录与参数白名单。

安全模型：
- 每个操作是一个"模板 + 命令拼接"，参数经过严格的 whitelist 校验后再用 shlex.quote
  包一层，双重保证参数不能进入任意 Shell 位置（无 shell 拼接注入面）。
- 任意命令作为 break_glass 能力，默认关闭，仅 admin 可启用（见 api/v1/exec_task.py）。
- 危险操作（写类，如 service_restart）标记 risk='write'，需要预览确认 + 幂等键。
"""
import json
import re
import shlex
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OperationParam:
    """操作参数定义：whitelist 校验规则。"""

    key: str
    label: str
    kind: str = 'str'          # str | int
    pattern: str | None = None  # 白名单正则（str 类型）
    min: int | None = None     # int 类型下限
    max: int | None = None     # int 类型上限
    default: str | None = None
    required: bool = False
    description: str = ''


@dataclass(frozen=True)
class Operation:
    """固定操作目录项。"""

    code: str
    name: str
    description: str
    risk: str                  # read | write
    params: list[OperationParam] = field(default_factory=list)
    build: callable = lambda params: ''   # 由参数构造最终命令（参数已白名单+quote）

    def validate_and_build(self, params: dict) -> str:
        """校验参数并通过模板构造命令。非法参数抛 ValueError。"""
        cleaned: dict[str, str] = {}
        for p in self.params:
            raw = params.get(p.key, p.default)
            if p.required and raw is None:
                raise ValueError(f'参数 {p.label} 必填')
            if raw is None:
                continue
            raw = str(raw).strip()
            if p.kind == 'int':
                if not raw.isdigit():
                    raise ValueError(f'参数 {p.label} 必须是整数')
                value = int(raw)
                if p.min is not None and value < p.min:
                    raise ValueError(f'参数 {p.label} 不能小于 {p.min}')
                if p.max is not None and value > p.max:
                    raise ValueError(f'参数 {p.label} 不能大于 {p.max}')
                cleaned[p.key] = str(value)
            else:
                if p.pattern and not re.match(p.pattern, raw):
                    raise ValueError(f'参数 {p.label} 不符合白名单规则')
                if len(raw) > 256:
                    raise ValueError(f'参数 {p.label} 过长')
                cleaned[p.key] = shlex.quote(raw)  # 二次防护：参数整体引用
        return self.build(cleaned)


# 参数白名单正则（服务名 / 绝对路径 / 无副作用的普通串）
_SERVICE = r'^[A-Za-z0-9_.:@-]{1,64}$'
_PATH = r'^/[A-Za-z0-9_./-]{1,200}$'
_PLAIN = r'^[A-Za-z0-9_.@-]{1,100}$'


def _df(params: dict) -> str:
    if 'path' in params:
        return f'df -h {params["path"]}'
    return 'df -h'


def _free(params: dict) -> str:
    return 'free -m'


def _service_status(params: dict) -> str:
    return f'systemctl status --no-pager {params["service"]} 2>&1 | head -40'


def _service_restart(params: dict) -> str:
    return f'systemctl restart {params["service"]} && systemctl is-active {params["service"]}'


def _log_tail(params: dict) -> str:
    if 'path' in params:
        return f'tail -n {params["lines"]} {params["path"]}'
    return f'tail -n {params["lines"]} /var/log/syslog'


def _port_listen(params: dict) -> str:
    if 'port' in params:
        return f'ss -tlnp | grep -E ":{params["port"]}\\b"'
    return 'ss -tlnp | head -40'


OPERATIONS: dict[str, Operation] = {
    op.code: op for op in [
        Operation(
            'disk_usage', '磁盘检查', '查看磁盘与分区使用情况（df -h）', 'read',
            [OperationParam('path', '路径（可选）', pattern=_PATH)],
            _df,
        ),
        Operation(
            'memory_usage', '内存检查', '查看内存与交换分区使用（free -m）', 'read',
            [], _free,
        ),
        Operation(
            'service_status', '服务状态', '查看 systemd 服务运行状态', 'read',
            [OperationParam('service', '服务名', pattern=_SERVICE, required=True,
                            description='如 nginx / docker / sshd')],
            _service_status,
        ),
        Operation(
            'service_restart', '服务重启', '重启 systemd 服务（写操作，需确认）', 'write',
            [OperationParam('service', '服务名', pattern=_SERVICE, required=True,
                            description='如 nginx / docker')],
            _service_restart,
        ),
        Operation(
            'log_tail', '日志尾部', '查看指定日志文件尾部 N 行', 'read',
            [
                OperationParam('lines', '行数', kind='int', min=1, max=200, default='50'),
                OperationParam('path', '日志文件绝对路径（可选）', pattern=_PATH,
                               description='默认 /var/log/syslog'),
            ],
            _log_tail,
        ),
        Operation(
            'port_listen', '端口监听', '查看端口监听情况（ss -tlnp）', 'read',
            [OperationParam('port', '端口（可选）', kind='int', min=1, max=65535)],
            _port_listen,
        ),
    ]
}

# break_glass 开关（system_flag 表键）
BREAK_GLASS_FLAG = 'break_glass_enabled'


def operation_list() -> list[dict]:
    """给前端/Swagger 用的目录列表。"""
    return [
        {
            'code': op.code, 'name': op.name, 'description': op.description, 'risk': op.risk,
            'params': [
                {'key': p.key, 'label': p.label, 'kind': p.kind, 'default': p.default,
                 'required': p.required, 'description': p.description}
                for p in op.params
            ],
        }
        for op in OPERATIONS.values()
    ]


def get_operation(code: str) -> Operation | None:
    return OPERATIONS.get(code)


def build_fixed_command(code: str, params: dict) -> str:
    """校验 + 构造固定操作命令。非法参数抛 ValueError。"""
    op = get_operation(code)
    if not op:
        raise ValueError(f'操作不存在: {code}')
    return op.validate_and_build(params)


def is_write_operation(code: str) -> bool:
    op = get_operation(code)
    return bool(op and op.risk == 'write')


def dump_params(params: dict) -> str:
    return json.dumps(params, ensure_ascii=False, sort_keys=True)