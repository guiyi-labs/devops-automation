from datetime import datetime

from pydantic import BaseModel, EmailStr


# ---------- 用户 ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    nickname: str
    email: EmailStr | None = None
    phone: str | None = None
    role_id: int = 1


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str
    email: str | None = None
    phone: str | None = None
    role_id: int
    role_name: str | None = None
    status: int

    class Config:
        from_attributes = True


# ---------- 资产 ----------
class AssetCreate(BaseModel):
    asset_name: str
    ip_address: str
    ssh_port: int = 22
    ssh_user: str
    ssh_pwd: str | None = None        # 明文入参只在请求体中出现，落库前加密
    ssh_key: str | None = None
    host_key_fingerprint: str | None = None
    os_type: str | None = None
    env_type: str = 'dev'
    business_group: str | None = None


class AssetUpdate(BaseModel):
    """部分更新：只更新调用方显式传入的字段。"""

    asset_name: str | None = None
    ip_address: str | None = None
    ssh_port: int | None = None
    ssh_user: str | None = None
    ssh_pwd: str | None = None
    ssh_key: str | None = None
    host_key_fingerprint: str | None = None
    os_type: str | None = None
    env_type: str | None = None
    business_group: str | None = None
    online_status: int | None = None
    cpu: str | None = None
    mem: str | None = None
    disk: str | None = None


class AssetOut(BaseModel):
    """资产输出：只暴露凭据存在性标记，绝不返回明文密码 / 私钥。"""

    id: int
    asset_name: str
    ip_address: str
    ssh_port: int
    ssh_user: str
    has_password: bool = False
    has_private_key: bool = False
    host_key_fingerprint: str | None = None
    os_type: str | None = None
    env_type: str
    business_group: str | None = None
    online_status: int
    cpu: str | None = None
    mem: str | None = None
    disk: str | None = None


# ---------- 批量执行（E3 受控操作） ----------
class BatchExecRequest(BaseModel):
    """受控执行请求。

    - operation + params：使用固定操作目录（推荐，防注入）；
    - command：break_glass 任意命令，仅 admin 且开关开启时可用；
    - idempotency_key：幂等键，同键不重复执行；
    - confirm_token：来自 /exec/preview 的确认令牌，写操作提交时必须携带。
    """
    asset_ids: list[int]
    operation: str | None = None
    params: dict = {}
    command: str | None = None          # break_glass 任意命令
    idempotency_key: str
    confirm_token: str | None = None


class ExecPreviewRequest(BaseModel):
    """预览请求：校验操作/参数/命令并生成确认令牌（不真正执行）。"""

    asset_ids: list[int]
    operation: str | None = None
    params: dict = {}
    command: str | None = None          # break_glass 任意命令


class ExecPreviewOut(BaseModel):
    asset_ids: list[int]
    hosts: list[str]
    operation: str | None
    command: str
    risk: str
    total_hosts: int
    confirm_token: str | None = None
    idempotency: bool = True


class ExecRecordOut(BaseModel):
    id: int
    asset_ids: str
    exec_type: str
    operation: str | None = None
    command: str
    exec_user: str
    status: str
    idempotency_key: str | None = None
    total_hosts: int = 0
    succeeded: int = 0
    failed: int = 0
    running: int = 0
    timed_out: int = 0
    exec_result: str | None = None

    class Config:
        from_attributes = True


class HostResultOut(BaseModel):
    id: int
    record_id: int
    asset_id: int
    host: str
    status: str
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    error_type: str | None = None
    error: str | None = None

    class Config:
        from_attributes = True


# ---------- E4 主机巡检 ----------
class InspectionRecordOut(BaseModel):
    id: int
    asset_ids: str
    status: str
    total_hosts: int = 0
    succeeded: int = 0
    failed: int = 0
    unknown: int = 0
    exec_user: str
    create_time: datetime | None = None

    class Config:
        from_attributes = True


class HostInspectionOut(BaseModel):
    id: int
    record_id: int | None
    asset_id: int
    host: str
    overall_status: str
    facts: str | None = None
    rule_results: str | None = None
    observed_at: datetime | None = None
    source: str = 'ssh'
    timeout_ms: int | None = None
    unavailable_reason: str | None = None

    class Config:
        from_attributes = True


class InspectionRuleIn(BaseModel):
    name: str
    description: str | None = None
    metric: str
    operator: str
    threshold: str
    severity: str = 'warning'
    enabled: int = 1


class InspectionRuleOut(InspectionRuleIn):
    id: int

    class Config:
        from_attributes = True


# ---------- 部署 ----------
class DeployProjectCreate(BaseModel):
    project_name: str
    git_url: str
    git_branch: str = 'main'
    build_script: str | None = None
    deploy_script: str | None = None
    env_type: str = 'dev'
    status: int = 1


class DeployProjectOut(DeployProjectCreate):
    id: int

    class Config:
        from_attributes = True


# ---------- 告警 ----------
class AlertRuleCreate(BaseModel):
    rule_name: str
    metric: str
    threshold: str
    level: str = '一般'
    webhook: str
    status: int = 1


class AlertRuleOut(AlertRuleCreate):
    id: int

    class Config:
        from_attributes = True


# ---------- Cron ----------
class CronTaskCreate(BaseModel):
    task_name: str
    cron_expr: str
    task_type: str
    task_content: str
    status: int = 1


class CronTaskOut(CronTaskCreate):
    id: int

    class Config:
        from_attributes = True