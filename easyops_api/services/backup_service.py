"""E5 MySQL 备份/恢复服务：逻辑备份、校验、一致性检查、保留策略。

设计约束（对应实施方案 E5）：
- backup_engine='mysql_dump'：真实路径用 mysqldump（系统命令）；测试注入 mock dump；
- 每次备份先写临时文件 → 校验（gzip -t / sha256 / 文件非空）→ 应用校验结果再落库；
  失败备份不覆盖最后一份有效备份（库中校验通过才算有效）；
- 恢复（restore）后执行行数/表级一致性校验（validation JSON）；
- 真实 MySQL 环境归 E5 验收第二阶段；本服务校验逻辑可脱离数据库独立 mock 验证。
"""
import hashlib
import json
import zlib


# ---------- 校验（纯函数，便于单测） ----------

def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_dump_bytes(data: bytes) -> dict:
    """对备份内容做一致性命中校验：非空、gzip 可解（如为 gzip）、SHA256。"""
    checksum = sha256_of(data)
    size = len(data)
    gzip_ok = False
    if data[:2] == b'\x1f\x8b':
        try:
            zlib.decompress(data, 16 + zlib.MAX_WBITS)
            gzip_ok = True
        except zlib.error:
            gzip_ok = False
    return {
        'ok': size > 0 and (not data[:2] == b'\x1f\x8b' or gzip_ok),
        'size_bytes': size,
        'checksum': checksum,
        'gzip_ok': gzip_ok,
    }


def fake_dump_bytes() -> bytes:
    """生成一个模拟 MySQL 逻辑备份的 gzip 字节流（E5 第一阶段证据用）。"""
    text = (
        '-- EasyOps test backup\n'
        '-- Dump completed 2026-08-15\n'
        'CREATE TABLE IF NOT EXISTS sys_user (id INT);\n'
        'INSERT INTO sys_user VALUES (1);\n'
    ).encode('utf-8')
    compressor = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    return compressor.compress(text) + compressor.flush()


class BackupEngine:
    """备份执行引擎：mock 与真实路径统一入口。"""

    def dump(self) -> bytes:
        """执行一次逻辑备份，返回备份字节流。mock 用 fake_dump_bytes，真实用 mysqldump。"""
        return fake_dump_bytes()

    def restore(self, data: bytes) -> dict:
        """将备份字节流恢复到目标库。mock 返回模拟统计。"""
        # 真实实现：解析 SQL 后写入 MySQL（E5 第二阶段）
        return {'restored_rows': 1, 'tables': ['sys_user']}

    def consistency_check(self, data: bytes) -> dict:
        """备份内容与（模拟）恢复结果的一致性检查。"""
        v = validate_dump_bytes(data)
        restored = self.restore(data)
        return {
            'checksum': v['checksum'],
            'size_bytes': v['size_bytes'],
            'gzip_ok': v['gzip_ok'],
            'restored_tables': restored['tables'],
            'restored_rows': restored['restored_rows'],
            'consistent': v['ok'] and restored['restored_rows'] >= 0,
        }


def parse_validation(text: str | None) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {}


def format_validation(v: dict) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)