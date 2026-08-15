"""E4 主机事实采集：一次 SSH 会话内执行只读探测命令，返回结构化 HostFacts。

安全与口径：
- 全部命令只读（hostname / uname / uptime / nproc / free / df / ss / systemctl
  is-active），不执行任何写操作；
- 复用 ssh_service 的主机密钥校验与错误分类；凭据在调用方解密，不进入消息；
- 逐探测独立容错：单个探测失败（如 ss 未安装）不拖垮整台采集，记录 unavailable_reason；
- 结果带 observed_at / source / timeout_ms，缺数据固定 unknown（不误判为健康）。
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

import paramiko

from common.redact import redact
from config import settings
from services.ssh_service import VerifyHostKeyPolicy

# 每台主机采集的软/硬超时
COLLECT_SOFT_TIMEOUT = 45
COLLECT_HARD_TIMEOUT = 60
_MAX_OUTPUT = 20000


@dataclass
class HostFacts:
    """单台主机的结构化巡检事实。磁盘/服务/端口均为 list。"""

    host: str
    hostname: str | None = None
    os_name: str | None = None
    kernel: str | None = None
    uptime: str | None = None
    cpu_count: int | None = None
    load_1: float | None = None
    load_5: float | None = None
    load_15: float | None = None
    memory_total_mb: int | None = None
    memory_used_mb: int | None = None
    swap_total_mb: int | None = None
    swap_used_mb: int | None = None
    disks: list[dict] = field(default_factory=list)      # [{mount,total_gb,used_gb,used_pct,inode_pct}]
    listening_ports: list[int] = field(default_factory=list)
    active_services: list[str] = field(default_factory=list)
    probes_failed: list[str] = field(default_factory=list)  # 探测失败的项目
    observed_at: str | None = None
    source: str = 'ssh'
    timeout_ms: int | None = None
    unavailable_reason: str | None = None

    @property
    def memory_used_pct(self) -> float | None:
        if not self.memory_total_mb:
            return None
        return round(self.memory_used_mb * 100 / self.memory_total_mb, 1)

    @property
    def swap_used_pct(self) -> float | None:
        if not self.swap_total_mb:
            return 0.0
        return round(self.swap_used_mb * 100 / self.swap_total_mb, 1)

    def to_dict(self) -> dict:
        return {
            'host': self.host, 'hostname': self.hostname, 'os_name': self.os_name,
            'kernel': self.kernel, 'uptime': self.uptime, 'cpu_count': self.cpu_count,
            'load_1': self.load_1, 'load_5': self.load_5, 'load_15': self.load_15,
            'memory_total_mb': self.memory_total_mb, 'memory_used_mb': self.memory_used_mb,
            'memory_used_pct': self.memory_used_pct,
            'swap_total_mb': self.swap_total_mb, 'swap_used_mb': self.swap_used_mb,
            'swap_used_pct': self.swap_used_pct,
            'disks': self.disks, 'listening_ports': self.listening_ports,
            'active_services': self.active_services, 'probes_failed': self.probes_failed,
            'observed_at': self.observed_at, 'source': self.source,
            'timeout_ms': self.timeout_ms, 'unavailable_reason': self.unavailable_reason,
        }


# ---------------- 纯解析函数（便于单测） ----------------

def parse_uptime(text: str) -> dict:
    """解析 `uptime` 输出：load average: 0.10, 0.20, 0.15"""
    match = re.search(r'load average:\s+([\d.]+),\s+([\d.]+),\s+([\d.]+)', text)
    if not match:
        return {}
    return {'load_1': float(match.group(1)), 'load_5': float(match.group(2)),
            'load_15': float(match.group(3))}


def parse_free_m(text: str) -> dict:
    """解析 `free -m` 输出：Mem/swap 总量与已用（MB）。"""
    result: dict[str, int | None] = {'memory_total_mb': None, 'memory_used_mb': None,
                                     'swap_total_mb': None, 'swap_used_mb': None}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == 'Mem:' and len(parts) >= 3:
            try:
                result['memory_total_mb'] = int(parts[1])
                result['memory_used_mb'] = int(parts[2])
            except ValueError:
                pass
        elif parts[0] == 'Swap:' and len(parts) >= 3:
            try:
                result['swap_total_mb'] = int(parts[1])
                result['swap_used_mb'] = int(parts[2])
            except ValueError:
                pass
    return result


def parse_df_h(text: str) -> list[dict]:
    """解析 `df -hP`：收集真实磁盘（排除 tmpfs/overlay/loop 等）。"""
    disks = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[0] == 'Filesystem' or parts[0] == '文件系统':
            continue
        fs, size, used, _, pct, mount = parts[0], parts[1], parts[2], parts[3], parts[4].rstrip('%'), parts[5]
        if fs.startswith(('tmpfs', 'overlay', 'shm', 'devtmpfs', 'loop', 'udev')):
            continue
        try:
            disks.append({
                'filesystem': fs,
                'mount': mount,
                'total_gb': round(float(size.rstrip('G').replace('T', 'G')) * (1024 if size.endswith('T') else 1), 1),
                'used_gb': round(float(used.rstrip('G').replace('T', 'G')) * (1024 if used.endswith('T') else 1), 1),
                'used_pct': float(pct),
            })
        except (ValueError, IndexError):
            continue
    return disks


def parse_df_i(text: str) -> dict[str, float]:
    """解析 `df -iP`：mount -> inode 使用率（%）。"""
    result: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[0] == 'Filesystem' or parts[0] == '文件系统':
            continue
        fs, _, _, _, pct, mount = parts[0], parts[1], parts[2], parts[3], parts[4].rstrip('%'), parts[5]
        if fs.startswith(('tmpfs', 'overlay', 'shm', 'devtmpfs', 'loop', 'udev')):
            continue
        try:
            result[mount] = float(pct)
        except ValueError:
            continue
    return result


def parse_ss_tln(text: str) -> list[int]:
    """解析 `ss -tln`：去重监听端口。"""
    ports = []
    for line in text.splitlines():
        match = re.search(r'LISTEN\s+\d+\s+\d+\s+\S+:(\d+)', line)
        if match and int(match.group(1)) not in ports:
            ports.append(int(match.group(1)))
    return sorted(ports)


def parse_os_release(text: str) -> str | None:
    """解析 /etc/os-release 的 PRETTY_NAME。"""
    match = re.search(r'^PRETTY_NAME="?([^"\n]+)"?', text, re.MULTILINE)
    return match.group(1).strip() if match else None


# ---------------- 采集执行 ----------------

def _open_ssh(asset, host_key_fingerprint: str | None, password: str | None = None,
              private_key: str | None = None, timeout: int = 30) -> paramiko.SSHClient:
    """建立带主机密钥校验的 SSH 会话（password/private_key 必须为解密后的明文）。"""
    from services.ssh_service import _load_private_key

    ssh = paramiko.SSHClient()
    policy = VerifyHostKeyPolicy(
        expected_fingerprint=host_key_fingerprint,
        allow_unverified=settings.SSH_ALLOW_UNVERIFIED_HOST_KEY and host_key_fingerprint is None,
    )
    ssh.set_missing_host_key_policy(policy)
    if host_key_fingerprint is None and not settings.SSH_ALLOW_UNVERIFIED_HOST_KEY:
        from services.ssh_service import UnknownHostKeyError
        raise UnknownHostKeyError(asset.ip_address, f'主机 {asset.ip_address} 未登记 host key，默认拒绝连接')
    pkey = _load_private_key(private_key) if private_key else None
    ssh.connect(
        asset.ip_address, port=asset.ssh_port, username=asset.ssh_user,
        password=password, pkey=pkey,
        timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
    )
    return ssh


def _run_probe(ssh: paramiko.SSHClient, cmd: str, timeout: int) -> str:
    """执行单条探测命令，非 0 退出或异常视为该探测失败，返回 stdout。"""
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        raise ValueError(f'{cmd} 退出码 {exit_code}: {err[:_MAX_OUTPUT]}')
    return out


def collect_host_facts(
    asset,
    password: str | None = None,
    private_key: str | None = None,
    host_key_fingerprint: str | None = None,
    soft_timeout: int = COLLECT_SOFT_TIMEOUT,
    hard_timeout: int = COLLECT_HARD_TIMEOUT,
) -> HostFacts:
    """采集一台主机的巡检事实。连接失败抛 ssh_service 可区分错误，其余失败记录在 facts。"""
    from common.crypto import decrypt_value

    facts = HostFacts(host=asset.ip_address)
    if password is None and asset.ssh_pwd:
        password = decrypt_value(asset.ssh_pwd)
    if private_key is None and asset.ssh_key:
        private_key = decrypt_value(asset.ssh_key)

    ssh = None
    try:
        ssh = _open_ssh(asset, host_key_fingerprint, password=password,
                        private_key=private_key, timeout=min(soft_timeout, 30))
        started = datetime.now()
        facts.observed_at = datetime.now().isoformat(timespec='seconds')

        def probe(cmd: str, key: str, parser):
            try:
                text = _run_probe(ssh, cmd, timeout=soft_timeout)
                parsed = parser(text)
                if parsed:
                    facts.__dict__.update(parsed)
            except Exception:
                facts.probes_failed.append(key)

        probe("hostname -f 2>/dev/null || hostname", 'hostname',
              lambda t: {'hostname': t.strip()} if t.strip() else {})
        probe("cat /etc/os-release 2>/dev/null | grep PRETTY_NAME",
              'os', lambda t: {'os_name': parse_os_release(t)})
        probe('uname -r', 'kernel', lambda t: {'kernel': t.strip()} if t.strip() else {})
        probe('uptime', 'uptime', parse_uptime)
        probe('nproc', 'cpu', lambda t: {'cpu_count': int(t.strip())} if t.strip().isdigit() else {})
        probe('free -m', 'memory', parse_free_m)
        probe('df -hP 2>/dev/null', 'disk', lambda t: {'disks': parse_df_h(t)})
        probe('df -iP 2>/dev/null', 'inode', lambda t: {'__inodes': parse_df_i(t)})
        probe('ss -tln 2>/dev/null || netstat -tln 2>/dev/null',
              'ports', lambda t: {'listening_ports': parse_ss_tln(t)})
        probe("systemctl list-units --type=service --state=running --no-legend 2>/dev/null",
              'services', lambda t: {
                  'active_services': sorted({line.split()[0].replace('.service', '') for line in t.splitlines()
                                              if line.strip()})})
        facts.timeout_ms = int((datetime.now() - started).total_seconds() * 1000)
        if '__inodes' in facts.__dict__:
            inode_map = facts.__dict__.pop('__inodes')
            for disk in facts.disks:
                disk['inode_pct'] = inode_map.get(disk['mount'])
    except Exception as exc:  # noqa: BLE001 连接/认证/超时等在 facts 上留痕，不抛出
        from services.ssh_service import (
            AuthError, ConnectionTimeoutError, HostKeyError, RemoteCommandError,
            UnknownHostKeyError, UnreachableError,
        )
        err_types = (AuthError, HostKeyError, UnknownHostKeyError,
                     ConnectionTimeoutError, UnreachableError, RemoteCommandError)
        error_type = exc.error_type if isinstance(exc, err_types) else 'ssh_error'
        facts.unavailable_reason = redact(str(exc))
        facts.probes_failed.append(f'connect:{error_type}')
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass
    return facts