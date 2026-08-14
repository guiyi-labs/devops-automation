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


# ---------- 批量执行 ----------
class BatchExecRequest(BaseModel):
    asset_ids: list[int]
    command: str


class ExecRecordOut(BaseModel):
    id: int
    asset_ids: str
    command: str
    exec_user: str
    exec_status: int
    exec_result: str | None = None

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