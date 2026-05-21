from pydantic import BaseModel, EmailStr
class LoginRequest(BaseModel): username: str; password: str
class UserCreate(BaseModel): username: str; password: str; nickname: str; email: EmailStr | None = None; phone: str | None = None; role_id: int = 1
class UserOut(BaseModel):
    id: int; username: str; nickname: str; email: str | None = None; phone: str | None = None; role_id: int; status: int
    class Config: from_attributes = True
class AssetCreate(BaseModel):
    asset_name: str; ip_address: str; ssh_port: int = 22; ssh_user: str; ssh_pwd: str | None = None; ssh_key: str | None = None; os_type: str | None = None; env_type: str = 'dev'; business_group: str | None = None
class AssetUpdate(AssetCreate): online_status: int = 0; cpu: str | None = None; mem: str | None = None; disk: str | None = None
class AssetOut(AssetUpdate):
    id: int
    class Config: from_attributes = True
class BatchExecRequest(BaseModel): asset_ids: list[int]; command: str
class ExecRecordOut(BaseModel):
    id: int; asset_ids: str; command: str; exec_user: str; exec_status: int; exec_result: str | None = None
    class Config: from_attributes = True
class DeployProjectCreate(BaseModel): project_name: str; git_url: str; git_branch: str = 'main'; build_script: str | None = None; deploy_script: str | None = None; env_type: str = 'dev'; status: int = 1
class DeployProjectOut(DeployProjectCreate):
    id: int
    class Config: from_attributes = True
class AlertRuleCreate(BaseModel): rule_name: str; metric: str; threshold: str; level: str = '一般'; webhook: str; status: int = 1
class AlertRuleOut(AlertRuleCreate):
    id: int
    class Config: from_attributes = True
class CronTaskCreate(BaseModel): task_name: str; cron_expr: str; task_type: str; task_content: str; status: int = 1
class CronTaskOut(CronTaskCreate):
    id: int
    class Config: from_attributes = True
