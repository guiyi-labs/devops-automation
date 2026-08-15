from sqlalchemy import Column, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import relationship

from database.session import Base


class TimestampMixin:
    create_time = Column(DateTime, nullable=False, server_default=func.now())
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class SysRole(Base):
    __tablename__ = 'sys_role'
    id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(50), nullable=False)
    role_code = Column(String(50), nullable=False, unique=True)
    description = Column(String(255))
    create_time = Column(DateTime, nullable=False, server_default=func.now())


class SysUser(Base, TimestampMixin):
    __tablename__ = 'sys_user'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False, unique=True, index=True)
    password = Column(String(128), nullable=False)
    nickname = Column(String(50), nullable=False)
    email = Column(String(100))
    phone = Column(String(20))
    role_id = Column(Integer, ForeignKey('sys_role.id'), nullable=False, default=1)
    status = Column(SmallInteger, nullable=False, default=1)

    role = relationship('SysRole', viewonly=True)

    @property
    def role_name(self) -> str | None:
        return self.role.role_name if self.role else None


class ServerAsset(Base, TimestampMixin):
    __tablename__ = 'server_asset'
    id = Column(Integer, primary_key=True, index=True)
    asset_name = Column(String(100), nullable=False)
    ip_address = Column(String(50), nullable=False, index=True)
    ssh_port = Column(Integer, nullable=False, default=22)
    ssh_user = Column(String(50), nullable=False)
    ssh_pwd = Column(String(512))        # 加密后的密码，见 common/crypto.py
    ssh_key = Column(Text)               # 加密后的私钥
    host_key_fingerprint = Column(String(255))  # 期望的主机密钥指纹（SHA256 base64）
    os_type = Column(String(50))
    env_type = Column(String(20), nullable=False, default='dev')
    business_group = Column(String(100))
    online_status = Column(SmallInteger, nullable=False, default=0)
    cpu = Column(String(50))
    mem = Column(String(50))
    disk = Column(String(50))


class ExecRecord(Base):
    """批量任务：一次用户发起的受控执行。包含幂等键与确认令牌。"""

    __tablename__ = 'exec_record'
    id = Column(Integer, primary_key=True, index=True)
    asset_ids = Column(String(255), nullable=False)
    # 操作类型: fixed(受控操作目录) | break_glass(任意命令，仅 admin)
    exec_type = Column(String(20), nullable=False, default='fixed')
    operation = Column(String(50))                  # fixed 时对应操作目录键
    params = Column(Text)                           # JSON 存储参数
    command = Column(Text, nullable=False)          # 规范化后的最终命令（脱敏安全）
    exec_user = Column(String(50), nullable=False)
    # 状态: pending(待确认) | confirmed(已确认待执行) | running | done | cancelled
    status = Column(String(20), nullable=False, default='pending')
    idempotency_key = Column(String(128), index=True)  # 幂等键（防重复提交）
    confirm_token = Column(String(64))              # 预览确认令牌，确认后清空
    worker_concurrency = Column(Integer, nullable=False, default=5)
    total_hosts = Column(Integer, nullable=False, default=0)
    succeeded = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    running = Column(Integer, nullable=False, default=0)
    timed_out = Column(Integer, nullable=False, default=0)
    exec_result = Column(Text)
    create_time = Column(DateTime, nullable=False, server_default=func.now())


class ExecHostResult(Base):
    """批任务单主机结果：每次针对一台主机的一次受控执行的状态与输出。"""

    __tablename__ = 'exec_host_result'
    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey('exec_record.id'), nullable=False, index=True)
    asset_id = Column(Integer, nullable=False, index=True)
    host = Column(String(50), nullable=False)
    # 状态: queued | running | succeeded | failed | timed_out | cancelled
    status = Column(String(20), nullable=False, default='queued')
    exit_code = Column(Integer)
    stdout = Column(Text)
    stderr = Column(Text)
    error_type = Column(String(50))
    error = Column(Text)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class DeployProject(Base):
    __tablename__ = 'deploy_project'
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String(100), nullable=False)
    git_url = Column(String(255), nullable=False)
    git_branch = Column(String(50), nullable=False, default='main')
    build_script = Column(Text)
    deploy_script = Column(Text)
    # E5-P2：真实发布只能绑定已登记、带 host-key 与加密凭据的资产。
    # 没有目标资产的历史项目仍可浏览，但 real executor 会 fail-closed。
    target_asset_id = Column(Integer, ForeignKey('server_asset.id'), nullable=True, index=True)
    env_type = Column(String(20), nullable=False)
    status = Column(SmallInteger, nullable=False, default=1)
    create_time = Column(DateTime, nullable=False, server_default=func.now())


class CronTask(Base):
    __tablename__ = 'cron_task'
    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(100), nullable=False)
    cron_expr = Column(String(50), nullable=False)
    task_type = Column(String(50), nullable=False)
    task_content = Column(Text, nullable=False)
    status = Column(SmallInteger, nullable=False, default=1)
    create_time = Column(DateTime, nullable=False, server_default=func.now())


class AlertRule(Base):
    __tablename__ = 'alert_rule'
    id = Column(Integer, primary_key=True, index=True)
    rule_name = Column(String(100), nullable=False)
    metric = Column(String(100), nullable=False)
    threshold = Column(String(50), nullable=False)
    level = Column(String(20), nullable=False)
    webhook = Column(String(255), nullable=False)
    status = Column(SmallInteger, nullable=False, default=1)


class AuditLog(Base):
    """审计日志：登录失败 / 权限拒绝 / 敏感操作。不记录任何明文凭据。"""

    __tablename__ = 'audit_log'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False, default='anonymous')
    action = Column(String(50), nullable=False)
    method = Column(String(10))
    path = Column(String(255))
    status_code = Column(Integer)
    ip_address = Column(String(50))
    detail = Column(String(512))
    create_time = Column(DateTime, nullable=False, server_default=func.now())


class SystemFlag(Base):
    """系统级开关，例如 init-admin 一次性 bootstrap 标记。"""

    __tablename__ = 'system_flag'
    id = Column(Integer, primary_key=True, index=True)
    flag_key = Column(String(50), nullable=False, unique=True)
    flag_value = Column(String(255), nullable=False)
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class HostInspection(Base, TimestampMixin):
    """单次主机巡检结果：一次 SSH 采集的事实与规则判定。"""

    __tablename__ = 'host_inspection'
    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey('inspection_record.id'), nullable=True, index=True)
    asset_id = Column(Integer, ForeignKey('server_asset.id'), nullable=False, index=True)
    host = Column(String(50), nullable=False)
    overall_status = Column(String(20), nullable=False, default='unknown')
    facts = Column(Text)              # JSON：采集到的结构化事实
    rule_results = Column(Text)       # JSON：规则判定明细
    observed_at = Column(DateTime, nullable=True)
    source = Column(String(20), nullable=False, default='ssh')
    timeout_ms = Column(Integer, nullable=True)
    unavailable_reason = Column(String(512), nullable=True)


class InspectionRecord(Base, TimestampMixin):
    """批量巡检任务记录：一次触发可能覆盖多台主机。"""

    __tablename__ = 'inspection_record'
    id = Column(Integer, primary_key=True, index=True)
    asset_ids = Column(String(512), nullable=False)
    status = Column(String(20), nullable=False, default='running')
    total_hosts = Column(Integer, nullable=False, default=0)
    succeeded = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    unknown = Column(Integer, nullable=False, default=0)
    exec_user = Column(String(50), nullable=False)


class InspectionRule(Base, TimestampMixin):
    """可配置巡检规则：metric + operator + threshold → severity。"""

    __tablename__ = 'inspection_rule'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255))
    metric = Column(String(50), nullable=False)      # disk_used_pct / swap_used_pct / load_5 / service_active / port_listening
    operator = Column(String(20), nullable=False)     # gt / lt / eq / ne / contains / not_contains
    threshold = Column(String(100), nullable=False)   # "90" / "nginx" / "80"
    severity = Column(String(20), nullable=False, default='warning')  # warning / critical
    enabled = Column(SmallInteger, nullable=False, default=1)


class DeployRelease(Base, TimestampMixin):
    """受控部署发布记录：一次 DeployProject 拉取/构建/部署/回滚的完整证据。"""

    __tablename__ = 'deploy_release'
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('deploy_project.id'), nullable=False, index=True)
    # 类型: preview(预览) | deploy(部署) | rollback(回滚)
    release_type = Column(String(20), nullable=False, default='deploy')
    # 状态: requested | running | succeeded | failed | rollback_succeeded | rollback_failed
    status = Column(String(30), nullable=False, default='requested')
    git_ref = Column(String(100))
    image = Column(String(255))                  # 构建出的镜像名
    image_digest = Column(String(255))           # 镜像 digest
    version = Column(String(50))
    exec_user = Column(String(50), nullable=False)
    result = Column(Text)                        # JSON：命令输出/回滚点/错误
    create_time = Column(DateTime, nullable=False, server_default=func.now())
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class BackupRecord(Base, TimestampMixin):
    """MySQL 逻辑备份/恢复记录：备份路径、校验、恢复点与保留策略。"""

    __tablename__ = 'backup_record'
    id = Column(Integer, primary_key=True, index=True)
    # 类型: backup | restore
    op_type = Column(String(20), nullable=False, default='backup')
    # 状态: running | succeeded | failed | verifying
    status = Column(String(20), nullable=False, default='running')
    file_path = Column(String(255))              # 备份文件（脱敏相对路径或占位）
    file_size_bytes = Column(Integer)            # 备份字节数
    mysql_dump_path = Column(String(255))        # mysqldump 可执行路径或 "embedded"
    backup_engine = Column(String(50), nullable=False, default='mysql_dump')
    database = Column(String(50))
    # 校验：sha256 / checksum / size_ok / row_count
    checksum = Column(String(64))
    checksum_ok = Column(SmallInteger, nullable=False, default=0)
    validation = Column(Text)                    # JSON：一致性校验结果
    exec_user = Column(String(50), nullable=False)
    result = Column(Text)                        # JSON：耗时/错误/恢复目标
    create_time = Column(DateTime, nullable=False, server_default=func.now())
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
