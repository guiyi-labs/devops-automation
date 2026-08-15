"""SSH 连接与命令执行，包含主机密钥校验和可区分的错误类型。

设计要点：
- 不使用 Paramiko AutoAddPolicy；默认拒绝未登记 host key 的主机；
- 已登记指纹的主机做严格校验，指纹不匹配拒绝连接；
- 认证失败 / 指纹不匹配 / 未登记密钥 / 连接超时 / 主机不可达 / 远端命令失败
  分别返回不同错误类型，便于前端和审计区分；
- 错误信息经过脱敏，不携带密码、私钥或 Token。
"""
import base64
import hashlib
import io

import paramiko

from common.redact import redact
from config import settings

_MAX_OUTPUT_BYTES = 10000


class SSHError(Exception):
    """SSH 错误基类，带 error_type 用于区分失败路径。"""

    error_type = 'ssh_error'

    def __init__(self, host: str, message: str):
        self.host = host
        super().__init__(message)


class AuthError(SSHError):
    error_type = 'auth_error'


class HostKeyError(SSHError):
    error_type = 'host_key_mismatch'


class UnknownHostKeyError(SSHError):
    error_type = 'unknown_host_key'


class ConnectionTimeoutError(SSHError):
    error_type = 'connection_timeout'


class UnreachableError(SSHError):
    error_type = 'unreachable'


class RemoteCommandError(SSHError):
    error_type = 'remote_command_failed'


def _compute_fingerprint(key: paramiko.PKey) -> str:
    """计算主机密钥的 SHA256/base64 指纹。"""
    digest = hashlib.sha256(key.asbytes()).digest()
    return base64.b64encode(digest).decode('ascii')


class VerifyHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """主机密钥校验策略：指纹匹配才接受；未登记且不允许时拒绝。"""

    def __init__(self, expected_fingerprint: str | None = None, allow_unverified: bool = False):
        self.expected_fingerprint = expected_fingerprint
        self.allow_unverified = allow_unverified

    def missing_host_key(self, client, hostname, key=None, host=None):
        # 兼容新旧两种调用风格：
        #   paramiko>=5.0: missing_host_key(client, hostname, key)
        #   paramiko<5.0 / 既有测试: missing_host_key(client, hostname, host, key)
        # （旧风格下 host 实参是 key，key 实参是 host）
        if key is None and host is not None:
            key, host = host, None
        actual = _compute_fingerprint(key)
        if self.expected_fingerprint:
            if actual != self.expected_fingerprint:
                raise HostKeyError(
                    hostname,
                    f'主机密钥指纹不匹配（期望 {self.expected_fingerprint}，实际 {actual}）',
                )
            return
        if not self.allow_unverified:
            raise UnknownHostKeyError(
                hostname,
                f'主机未登记 host key（实际指纹 {actual}），默认拒绝连接',
            )
        # host 仅在旧风格下非空；新风格下 host=None，用 keytype 名作为存储键
        if host is not None:
            client._host_keys.add(hostname, host, key)
        else:
            keytype = key.get_name() if hasattr(key, 'get_name') else 'ssh-host-key'
            client._host_keys.add(hostname, keytype, key)


def _load_private_key(private_key_text: str) -> paramiko.PKey | None:
    """尝试按常见密钥类型加载私钥文本（DSS 已随 paramiko 5 移除，不再支持）。"""
    for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_class.from_private_key(io.StringIO(private_key_text))
        except paramiko.ssh_exception.SSHException:
            continue
    return None


def connect_and_run(
    host: str,
    port: int,
    user: str,
    password: str | None = None,
    private_key: str | None = None,
    cmd: str = '',
    host_key_fingerprint: str | None = None,
    timeout: int = 30,
    cmd_timeout: int = 60,
) -> dict:
    """连接 SSH 并执行命令，返回带 stdout/stderr/exit_code 的结果。

    可能抛出的错误（error_type 可区分）：
        UnknownHostKeyError / HostKeyError / AuthError /
        ConnectionTimeoutError / UnreachableError / RemoteCommandError
    """
    ssh = paramiko.SSHClient()
    policy = VerifyHostKeyPolicy(
        expected_fingerprint=host_key_fingerprint,
        allow_unverified=settings.SSH_ALLOW_UNVERIFIED_HOST_KEY and host_key_fingerprint is None,
    )
    ssh.set_missing_host_key_policy(policy)

    # 提前校验：既无指纹、又未允许未验证时直接拒绝，避免无谓的连接尝试
    if host_key_fingerprint is None and not settings.SSH_ALLOW_UNVERIFIED_HOST_KEY:
        raise UnknownHostKeyError(host, f'主机 {host} 未登记 host key，默认拒绝连接')

    pkey = _load_private_key(private_key) if private_key else None

    try:
        ssh.connect(
            host, port=port, username=user,
            password=password, pkey=pkey,
            timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
        )
        _, stdout, stderr = ssh.exec_command(cmd, timeout=cmd_timeout)
        out = stdout.read().decode('utf-8', errors='ignore')
        err = stderr.read().decode('utf-8', errors='ignore')
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            raise RemoteCommandError(
                host, f'远端命令执行失败（exit={exit_code}）：{err[:_MAX_OUTPUT_BYTES]}'
            )
        return {
            'host': host,
            'stdout': out[:_MAX_OUTPUT_BYTES],
            'stderr': err[:_MAX_OUTPUT_BYTES],
            'exit_code': exit_code,
            'status': 1,
        }
    except (AuthError, HostKeyError, UnknownHostKeyError, RemoteCommandError):
        raise
    except paramiko.AuthenticationException:
        raise AuthError(host, f'SSH 认证失败（{user}@{host}）')
    except paramiko.ssh_exception.NoValidConnectionsError as exc:
        raise UnreachableError(host, f'主机不可达（{host}:{port}）：{redact(str(exc))}')
    except Exception as exc:
        message = str(exc).lower()
        if 'timeout' in message or 'timed out' in message:
            raise ConnectionTimeoutError(host, f'SSH 连接超时（{host}:{port}）')
        raise UnreachableError(host, f'SSH 连接失败（{host}:{port}）：{redact(str(exc))}')
    finally:
        try:
            ssh.close()
        except Exception:
            pass