"""日志与异常脱敏。

在应用日志、异常堆栈和审计记录中过滤密码、私钥、Token 和数据库 URL。
"""
from __future__ import annotations

import logging
import re
from typing import List

# 按正则匹配敏感信息，匹配到的内容替换为 [REDACTED]
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'password[=:]\s*\S+', re.IGNORECASE), '[REDACTED]'),
    (re.compile(r'private.?key[=:]\s*\S+', re.IGNORECASE), '[REDACTED]'),
    (re.compile(r'token[=:]\s*\S+', re.IGNORECASE), '[REDACTED]'),
    (re.compile(r'mysql\+pymysql://\S+', re.IGNORECASE), '[REDACTED_DB_URL]'),
    (re.compile(r'redis://\S+', re.IGNORECASE), '[REDACTED_REDIS_URL]'),
    (re.compile(r'v1:[A-Za-z0-9_=\-]+'), '[REDACTED_ENCRYPTED]'),
]

_known_secrets: List[str] = []


def register_secret(secret: str) -> None:
    """注册一个需要脱敏的敏感字符串（长度 > 3 才生效）。"""
    if secret and len(secret) > 3 and secret not in _known_secrets:
        _known_secrets.append(secret)


def redact(text: str) -> str:
    """对字符串进行脱敏：替换正则匹配项 + 所有已注册的 Secret。"""
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    # 按长度降序，优先替换较长的 Secret
    for secret in sorted(_known_secrets, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    return text


class LogRedactFilter(logging.Filter):
    """logging 过滤器：对每条日志的 msg 和 args 进行脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    redact(str(a)) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: redact(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True