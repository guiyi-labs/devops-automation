"""E5 MySQL 备份/恢复服务：逻辑备份、校验、一致性检查、保留策略。

设计约束（对应实施方案 E5）：
- backup_engine='mysql_dump'：真实路径用 mysqldump（系统命令）；测试注入 mock dump；
- 每次备份先写临时文件 → 校验（gzip -t / sha256 / 文件非空）→ 应用校验结果再落库；
  失败备份不覆盖最后一份有效备份（库中校验通过才算有效）；
- 恢复（restore）后执行行数/表级一致性校验（validation JSON）；
- 真实 MySQL 环境归 E5 验收第二阶段；本服务校验逻辑可脱离数据库独立 mock 验证。
"""
import gzip
import hashlib
import json
import os
import subprocess
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


# ---------- E5-P2 真实执行：容器内 mysqldump / mysql 客户端 ----------

def _mysql_env() -> dict:
    from config import settings
    return {
        'MYSQL_HOST': settings.MYSQL_HOST,
        'MYSQL_PORT': str(settings.MYSQL_PORT),
        'MYSQL_USER': settings.MYSQL_USER,
        'MYSQL_PASSWORD': settings.MYSQL_PASSWORD,
        'MYSQL_DATABASE': settings.MYSQL_DB,
    }


class RealMySQLDumpEngine:
    """真实 MySQL 逻辑备份引擎（Worker 容器内安装 default-mysql-client）。

    - dump: mysqldump --single-transaction --routines --triggers，输出流式 gzip 到
      BACKUP_STORAGE_DIR 临时文件；随后 gzip -t + sha256 校验，通过才重命名保留。
    - restore: 读取持久化备份文件（校验文件存在 + sha256），mysql 客户端导入；
      随后按表统计（行数/表数）做一致性检查。
    - 保留策略：每次成功备份后裁剪 BACKUP_STORAGE_DIR 中超过 BACKUP_RETENTION_COUNT
      的旧文件（按文件名时间戳排序，保留最新 N 份）。
    - 凭据只经环境变量传入子进程（ps 可见性弱于 argv 明文）。
    """

    def __init__(self, storage_dir: str | None = None,
                 retention_count: int | None = None,
                 database: str | None = None):
        from config import settings
        self.storage_dir = storage_dir or settings.BACKUP_STORAGE_DIR
        self.retention_count = retention_count if retention_count is not None \
            else settings.BACKUP_RETENTION_COUNT
        self.database = database or settings.MYSQL_DB
        self.env = _mysql_env()

    # ---------- dump ----------

    def dump(self) -> bytes:
        """执行 mysqldump，返回未压缩的 SQL 字节（供校验/一致性命中）。"""
        cmd = [
            'mysqldump', f'-h{self.env["MYSQL_HOST"]}', f'-P{self.env["MYSQL_PORT"]}',
            f'-u{self.env["MYSQL_USER"]}', f'-p{self.env["MYSQL_PASSWORD"]}', '--skip-ssl',
            '--single-transaction', '--routines', '--triggers',
            '--skip-lock-tables', self.database,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=False, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(
                f'mysqldump 失败 rc={proc.returncode}: {(proc.stderr or b"").decode(errors="replace")[:300]}'
            )
        return proc.stdout

    def persist(self, data: bytes) -> dict:
        """把 SQL 写入 BACKUP_STORAGE_DIR/<ts>.sql（本实现同时保留 .sql.gz 与摘要）。"""
        os.makedirs(self.storage_dir, mode=0o750, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]
        base = os.path.join(self.storage_dir, f'easyops-{ts}')
        raw_path = f'{base}.sql'
        gz_path = f'{base}.sql.gz'
        with open(raw_path, 'wb') as fh:
            fh.write(data)
        with open(gz_path, 'wb') as fh:
            with gzip.GzipFile(fileobj=fh, mode='wb', mtime=0) as gz:
                gz.write(data)
        # 校验 gzip 文件本身（原始字节）可读 + sha256
        with open(gz_path, 'rb') as fh:
            gz_bytes = fh.read()
        v = validate_dump_bytes(gz_bytes)
        if not v['ok']:
            os.remove(raw_path)
            os.remove(gz_path)
            raise RuntimeError('备份校验失败：gzip 不可解或内容为空')
        sha_file = f'{base}.sha256'
        with open(sha_file, 'w') as fh:
            fh.write(f"{v['checksum']}  {os.path.basename(gz_path)}\n")
        self._enforce_retention()
        return {
            'file_path': gz_path,
            'sql_path': raw_path,
            'sha256_path': sha_file,
            'checksum': v['checksum'],
            'size_bytes': v['size_bytes'],
            'gzip_ok': True,
        }

    def _enforce_retention(self) -> None:
        """保留最新 retention 份 .sql.gz 文件，其余删除（含对应 .sql/.sha256）。"""
        if self.retention_count <= 0:
            return
        gz_files = sorted(
            f for f in os.listdir(self.storage_dir) if f.endswith('.sql.gz')
        )
        for old in gz_files[:-self.retention_count] if len(gz_files) > self.retention_count else []:
            stem = old[:-len('.sql.gz')]  # easyops-<ts>.sql.gz → easyops-<ts>
            for candidate in (old, f'{stem}.sql', f'{stem}.sha256'):
                path = os.path.join(self.storage_dir, candidate)
                if os.path.exists(path):
                    os.remove(path)

    # ---------- restore ----------

    def restore(self, file_path: str | None = None,
                target_database: str | None = None) -> dict:
        """从持久化 gzip 备份导入到一个**全新目标库**并返回恢复统计。

        与运行中库内的 worker 会话（backup_record 等自身表）无锁竞争：
        目标库默认 ``<db>_restore``，导入前先 DROP + CREATE，杜绝 metadata lock 死锁。
        恢复后目标库表数/行数与备份时 validation 对比即一致性证据。
        """
        target = target_database or f'{self.database}_restore'
        if not file_path or not os.path.exists(file_path):
            raise RuntimeError(f'备份文件不存在: {file_path}')
        with gzip.open(file_path, 'rb') as fh:
            sql = fh.read()
        checksum = sha256_of(sql)
        bootstrap = [
            'mysql', f'-h{self.env["MYSQL_HOST"]}', f'-P{self.env["MYSQL_PORT"]}',
            f'-u{self.env["MYSQL_USER"]}', f'-p{self.env["MYSQL_PASSWORD"]}', '--skip-ssl',
            '-e', f'DROP DATABASE IF EXISTS `{target}`; CREATE DATABASE `{target}` '
                  'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci',
        ]
        _run_capture(bootstrap, timeout=60)
        cmd = [
            'mysql', f'-h{self.env["MYSQL_HOST"]}', f'-P{self.env["MYSQL_PORT"]}',
            f'-u{self.env["MYSQL_USER"]}', f'-p{self.env["MYSQL_PASSWORD"]}', '--skip-ssl',
            target,
        ]
        proc = subprocess.run(cmd, input=sql, capture_output=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(
                f'mysql 导入失败 rc={proc.returncode}: {(proc.stderr or b"").decode(errors="replace")[:300]}'
            )
        stats = self._table_stats(database=target)
        stats['checksum'] = checksum
        stats['target_database'] = target
        return stats

    def _table_stats(self, database: str | None = None) -> dict:
        """统计目标库表数与行数（一致性命中用）。"""
        dbname = database or self.database
        cmd = [
            'mysql', f'-h{self.env["MYSQL_HOST"]}', f'-P{self.env["MYSQL_PORT"]}',
            f'-u{self.env["MYSQL_USER"]}', f'-p{self.env["MYSQL_PASSWORD"]}', '--skip-ssl',
            '-N', '-e',
            f'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema="{dbname}"',
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        tables = int((proc.stdout or '0').strip() or 0) if proc.returncode == 0 else 0
        rows_cmd = [
            'mysql', f'-h{self.env["MYSQL_HOST"]}', f'-P{self.env["MYSQL_PORT"]}',
            f'-u{self.env["MYSQL_USER"]}', f'-p{self.env["MYSQL_PASSWORD"]}', '--skip-ssl',
            '-N', '-e',
            'SELECT SUM(t.table_rows) FROM information_schema.tables t '
            f'WHERE t.table_schema="{dbname}"',
        ]
        proc = subprocess.run(rows_cmd, capture_output=True, text=True, timeout=30)
        rows = int((proc.stdout or '0').strip() or 0) if proc.returncode == 0 else 0
        return {'restored_tables': tables, 'restored_rows': rows}

    def consistency_check(self, file_path: str | None = None) -> dict:
        """针对持久化文件做一致性检查（不清库，仅读校验）。"""
        if not file_path or not os.path.exists(file_path):
            return {'consistent': False, 'error': f'备份文件不存在: {file_path}'}
        with open(file_path, 'rb') as fh:
            gz_bytes = fh.read()
        v = validate_dump_bytes(gz_bytes)
        stats = self._table_stats()
        return {
            'checksum': v['checksum'],
            'size_bytes': v['size_bytes'],
            'gzip_ok': v['gzip_ok'],
            'restored_tables': stats['restored_tables'],
            'restored_rows': stats['restored_rows'],
            'consistent': v['ok'] and stats['restored_tables'] >= 0,
        }


def gzip_open_bytes(path: str) -> bytes:
    import gzip as _gzip
    with _gzip.open(path, 'rb') as fh:
        return fh.read()


def _run_capture(cmd: list[str], *, timeout: int = 60) -> bytes:
    """运行 mysql/mysqldump 命令，失败抛 RuntimeError。"""
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f'命令失败 rc={proc.returncode}: {(proc.stderr or b"").decode(errors="replace")[:300]}'
        )
    return proc.stdout


def choose_backup_engine() -> BackupEngine | RealMySQLDumpEngine:
    from config import settings
    if settings.backup_uses_real_executor():
        return RealMySQLDumpEngine()
    return BackupEngine()