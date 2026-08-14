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
    __tablename__ = 'exec_record'
    id = Column(Integer, primary_key=True, index=True)
    asset_ids = Column(String(255), nullable=False)
    command = Column(Text, nullable=False)
    exec_user = Column(String(50), nullable=False)
    exec_status = Column(SmallInteger, nullable=False, default=0)
    exec_result = Column(Text)
    create_time = Column(DateTime, nullable=False, server_default=func.now())


class DeployProject(Base):
    __tablename__ = 'deploy_project'
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String(100), nullable=False)
    git_url = Column(String(255), nullable=False)
    git_branch = Column(String(50), nullable=False, default='main')
    build_script = Column(Text)
    deploy_script = Column(Text)
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