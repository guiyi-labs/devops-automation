"""E4 主机巡检测试：事实解析、规则引擎、API 与 Worker（mock SSH 采集）。

mock/单测口径：不连接真实主机；collect_host_facts 的 SSH 在 worker 测试中整体替换。
"""
from unittest.mock import patch

from services import inspection_rules
from services.host_inspection import (
    HostFacts, parse_df_h, parse_df_i, parse_free_m, parse_ss_tln, parse_uptime,
)
from tasks.inspection_tasks import inspect_host


class _FakeGroup:
    def __init__(self, *args, **kwargs):
        self.id = 'fake-inspection-group'

    def __call__(self, *args, **kwargs):
        return self


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _create_asset(client, token, ip, name='box', pwd='pw123'):
    resp = client.post('/api/v1/asset/', json={
        'asset_name': name, 'ip_address': ip, 'ssh_user': 'root', 'ssh_pwd': pwd,
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- 事实解析 ----------
def test_parse_uptime():
    assert parse_uptime(' 09:30:01 up 10 days,  2:30,  3 users,  load average: 0.52, 0.45, 0.38') == {
        'load_1': 0.52, 'load_5': 0.45, 'load_15': 0.38}
    assert parse_uptime('no load here') == {}


def test_parse_free_m():
    text = '              total        used        free      shared  buff/cache   available\n' \
           'Mem:           7817        5120         645         118        2051        2355\n' \
           'Swap:          2048         512        1536\n'
    assert parse_free_m(text) == {
        'memory_total_mb': 7817, 'memory_used_mb': 5120,
        'swap_total_mb': 2048, 'swap_used_mb': 512}


def test_parse_df_h_filters_virtual():
    text = """Filesystem      Size  Used Avail Use% Mounted on
overlay          100G   80G   20G  80% /
tmpfs           1000M     0  1000M   0% /dev
/dev/sda1       100G   92G  8.0G  92% /data
/dev/loop0       55M   55M     0 100% /snap/foo
udev            465M   12K  465M   1% /dev
/dev/sdb1       200G   20G  180G  10% /var/lib/mysql"""
    disks = parse_df_h(text)
    mounts = [d['mount'] for d in disks]
    assert mounts == ['/data', '/var/lib/mysql']  # overlay/tmpfs/loop/udev 被过滤
    assert disks[0]['used_pct'] == 92.0


def test_parse_df_i():
    text = """Filesystem     Inodes IUsed IFree IUse% Mounted on
/dev/sda1      6553600 6000000  553600   92% /data
overlay       10000000     100 9999900    1% /
"""
    inodes = parse_df_i(text)
    assert inodes == {'/data': 92.0}


def test_parse_ss_tln():
    text = """State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port Process
LISTEN   0       128          0.0.0.0:22          0.0.0.0:*    users:(("sshd",pid=1,fd=3))
LISTEN   0       128          0.0.0.0:80          0.0.0.0:*    users:(("nginx",pid=2,fd=4))
LISTEN   0       128             [::]:22          0.0.0.0:*    users:(("sshd",pid=1,fd=5))
ESTAB    0       0           10.0.0.1:22          10.0.0.2:44872
"""
    assert parse_ss_tln(text) == [22, 80]  # 去重、ESTAB 过滤


# ---------- 规则引擎 ----------
def _facts(overrides=None):
    f = HostFacts(host='10.0.0.1', load_5=1.0, memory_used_mb=4000, memory_total_mb=8000,
                  swap_used_mb=0, swap_total_mb=2048,
                  disks=[{'mount': '/', 'used_pct': 60.0, 'inode_pct': 30.0}],
                  listening_ports=[22, 80], active_services=['nginx', 'sshd'])
    d = f.to_dict()
    if overrides:
        d.update(overrides)
    return d


def test_rule_engine_healthy():
    rules = inspection_rules.default_rules()
    assessment = inspection_rules.evaluate(_facts(), rules)
    assert assessment.overall == 'healthy'


def test_rule_engine_disk_warning_and_critical():
    rules = inspection_rules.default_rules()
    # 磁盘 92% → warning（>90），未到 critical（>95）
    assessment = inspection_rules.evaluate(
        _facts({'disks': [{'mount': '/', 'used_pct': 92.0, 'inode_pct': 30.0}]}), rules)
    assert assessment.overall == 'warning'
    # 磁盘 97% → critical
    assessment = inspection_rules.evaluate(
        _facts({'disks': [{'mount': '/', 'used_pct': 97.0, 'inode_pct': 30.0}]}), rules)
    assert assessment.overall == 'critical'


def test_rule_engine_swap_and_load():
    rules = inspection_rules.default_rules()
    assert inspection_rules.evaluate(_facts({'swap_used_pct': 60.0}), rules).overall == 'warning'
    assert inspection_rules.evaluate(_facts({'load_5': 8.5}), rules).overall == 'warning'


def test_rule_engine_service_stopped_and_port():
    rules = inspection_rules.default_rules()
    # nginx 不在运行列表 → service_stopped 命中（critical）
    assert inspection_rules.evaluate(
        _facts({'active_services': ['sshd']}), rules).overall == 'critical'
    # SSH 22 端口未监听 → port_not_listening 命中（warning）
    assert inspection_rules.evaluate(
        _facts({'listening_ports': [80]}), rules).overall == 'warning'


def test_rule_engine_unavailable_is_unknown():
    """缺数据固定 unknown，不误判为健康。"""
    rules = inspection_rules.default_rules()
    facts = _facts()
    facts['unavailable_reason'] = 'SSH 认证失败'
    assessment = inspection_rules.evaluate(facts, rules)
    assert assessment.overall == 'unknown'


def test_rule_engine_no_rules_unknown():
    assert inspection_rules.evaluate(_facts(), []).overall == 'unknown'


# ---------- API ----------
def test_inspection_collect_creates_record(client, admin_token):
    asset = _create_asset(client, admin_token, '10.1.1.1')
    with patch('api.v1.inspection.group', _FakeGroup):
        resp = client.post('/api/v1/inspection/collect',
                           json={'asset_ids': [asset['id']]}, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['total_hosts'] == 1
    records = client.get('/api/v1/inspection/records', headers=_auth(admin_token)).json()
    assert len(records) == 1
    hosts = client.get(f"/api/v1/inspection/records/{body['record_id']}/hosts",
                       headers=_auth(admin_token)).json()
    assert hosts[0]['overall_status'] == 'running'


def test_inspection_collect_empty_and_missing(client, admin_token):
    resp = client.post('/api/v1/inspection/collect', json={'asset_ids': []},
                       headers=_auth(admin_token))
    assert resp.status_code == 400
    resp = client.post('/api/v1/inspection/collect', json={'asset_ids': [99999]},
                       headers=_auth(admin_token))
    assert resp.status_code == 400


def test_inspection_rules_seeded_and_crud(client, admin_token):
    # collect 触发默认规则种子
    asset = _create_asset(client, admin_token, '10.1.1.2')
    with patch('api.v1.inspection.group', _FakeGroup):
        client.post('/api/v1/inspection/collect', json={'asset_ids': [asset['id']]},
                    headers=_auth(admin_token))
    rules = client.get('/api/v1/inspection/rules', headers=_auth(admin_token)).json()
    assert len(rules) >= 8
    # 新增规则
    resp = client.post('/api/v1/inspection/rules', json={
        'name': 'test-port-443', 'metric': 'port_not_listening', 'operator': 'not_contains',
        'threshold': '443', 'severity': 'warning'}, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    rule_id = resp.json()['id']
    # 重复名 409
    resp = client.post('/api/v1/inspection/rules', json={
        'name': 'test-port-443', 'metric': 'port_not_listening', 'operator': 'not_contains',
        'threshold': '443', 'severity': 'warning'}, headers=_auth(admin_token))
    assert resp.status_code == 409
    # 非法指标 400
    resp = client.post('/api/v1/inspection/rules', json={
        'name': 'bad', 'metric': 'nope', 'operator': 'gt', 'threshold': '1', 'severity': 'warning'},
        headers=_auth(admin_token))
    assert resp.status_code == 400
    # 更新 + 删除
    resp = client.put(f'/api/v1/inspection/rules/{rule_id}', json={
        'name': 'test-port-443', 'metric': 'port_not_listening', 'operator': 'not_contains',
        'threshold': '8443', 'severity': 'critical'}, headers=_auth(admin_token))
    assert resp.status_code == 200
    resp = client.delete(f'/api/v1/inspection/rules/{rule_id}', headers=_auth(admin_token))
    assert resp.status_code == 200


def test_inspection_permission_viewer(client, viewer_token):
    resp = client.post('/api/v1/inspection/collect', json={'asset_ids': [1]},
                       headers=_auth(viewer_token))
    assert resp.status_code in (400, 403)


# ---------- Worker ----------
def test_inspect_worker_healthy(client, admin_token):
    asset = _create_asset(client, admin_token, '10.2.2.2')
    with patch('api.v1.inspection.group', _FakeGroup):
        body = client.post('/api/v1/inspection/collect', json={'asset_ids': [asset['id']]},
                           headers=_auth(admin_token)).json()

    fake = HostFacts(host='10.2.2.2', hostname='box', os_name='Ubuntu 24.04',
                     load_5=1.2, memory_used_mb=2048, memory_total_mb=8192,
                     disks=[{'mount': '/', 'used_pct': 55.0, 'inode_pct': 20.0}],
                     listening_ports=[22, 80], active_services=['nginx', 'sshd'],
                     observed_at='2026-08-15T10:00:00')

    with patch('tasks.inspection_tasks.collect_host_facts', return_value=fake):
        result = inspect_host.run(body['record_id'], asset['id'])
    assert result['overall_status'] == 'healthy'
    hosts = client.get(f"/api/v1/inspection/records/{body['record_id']}/hosts",
                       headers=_auth(admin_token)).json()
    assert hosts[0]['overall_status'] == 'healthy'


def test_inspect_worker_critical_disk(client, admin_token):
    asset = _create_asset(client, admin_token, '10.2.2.3')
    with patch('api.v1.inspection.group', _FakeGroup):
        body = client.post('/api/v1/inspection/collect', json={'asset_ids': [asset['id']]},
                           headers=_auth(admin_token)).json()
    fake = HostFacts(host='10.2.2.3', load_5=1.0, memory_used_mb=1024, memory_total_mb=8192,
                     disks=[{'mount': '/', 'used_pct': 98.0, 'inode_pct': 20.0}],
                     listening_ports=[22], active_services=['sshd', 'nginx'],  # nginx 存在 → service 规则健康
                     observed_at='2026-08-15T10:00:00')
    with patch('tasks.inspection_tasks.collect_host_facts', return_value=fake):
        result = inspect_host.run(body['record_id'], asset['id'])
    assert result['overall_status'] == 'critical'


def test_inspect_worker_unavailable_unknown(client, admin_token):
    asset = _create_asset(client, admin_token, '10.2.2.4')
    with patch('api.v1.inspection.group', _FakeGroup):
        body = client.post('/api/v1/inspection/collect', json={'asset_ids': [asset['id']]},
                           headers=_auth(admin_token)).json()
    fake = HostFacts(host='10.2.2.4', unavailable_reason='SSH 认证失败')
    with patch('tasks.inspection_tasks.collect_host_facts', return_value=fake):
        result = inspect_host.run(body['record_id'], asset['id'])
    assert result['overall_status'] == 'unknown'
    assert result['unavailable'] is True


def test_inspect_worker_missing_asset(client, admin_token):
    asset = _create_asset(client, admin_token, '10.2.2.5')
    with patch('api.v1.inspection.group', _FakeGroup):
        body = client.post('/api/v1/inspection/collect', json={'asset_ids': [asset['id']]},
                           headers=_auth(admin_token)).json()
    result = inspect_host.run(body['record_id'], 999999)
    assert result['status'] == 2
    assert '不存在' in result['error']

# ---------- collect_host_facts（mock SSH） ----------
def _fake_ssh():
    class _FakeSSH:
        def __init__(self):
            self.cmds = []

        def exec_command(self, cmd, timeout=None):
            self.cmds.append(cmd)
            responses = {
                "hostname -f 2>/dev/null || hostname": 'box.example.com\n',
                "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME": 'PRETTY_NAME="Ubuntu 24.04"\n',
                "uname -r": '6.8.0-45-generic\n',
                "uptime": 'load average: 0.60, 0.50, 0.40\n',
                "nproc": '8\n',
                "free -m": 'Mem: 8192  2048  6000   0   144  5800\nSwap: 2048 0 2048\n',
                'df -hP 2>/dev/null': 'Filesystem Size Used Avail Use% Mounted on\n/dev/sda1 100G 40G 60G 40% /\n',
                'df -iP 2>/dev/null': 'Filesystem Inodes IUsed IFree IUse% Mounted on\n/dev/sda1 6553600 300000 6253600 5% /\n',
                "ss -tln 2>/dev/null || netstat -tln 2>/dev/null": 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n',
                "systemctl list-units --type=service --state=running --no-legend 2>/dev/null": 'nginx.service running\nsshd.service running\n',
            }
            content = responses.get(cmd, '')
            class _Out:
                def read(self): return content.encode()
                channel = type('Ch', (), {'recv_exit_status': lambda s: 0})()
            class _Err:
                def read(self): return b''
                channel = type('Ch', (), {'recv_exit_status': lambda s: 0})()
            return None, _Out(), _Err()

        def close(self): pass
    return _FakeSSH()


def test_collect_host_facts_full_collection(client, admin_token):
    """完整采集：事实字段齐全、observed_at/timeout 有值。"""
    fake = _fake_ssh()
    with patch('services.host_inspection._open_ssh', return_value=fake):
        facts = _facts_collect(client, admin_token, '10.3.3.1')
    assert facts.hostname == 'box.example.com'
    assert facts.os_name == 'Ubuntu 24.04'
    assert facts.kernel == '6.8.0-45-generic'
    assert facts.load_1 == 0.6
    assert facts.cpu_count == 8
    assert facts.memory_total_mb == 8192
    assert facts.disks and facts.disks[0]['mount'] == '/'
    assert 22 in facts.listening_ports
    assert facts.active_services == ['nginx', 'sshd']
    assert facts.observed_at is not None
    assert facts.timeout_ms is not None
    assert facts.unavailable_reason is None


def _facts_collect(client, token, ip):
    """创建资产并从 DB 取 ORM 对象，调用真实 collect_host_facts（_open_ssh 已被 mock）。"""
    from database.models import ServerAsset
    from database.session import SessionLocal
    from services.host_inspection import collect_host_facts

    _create_asset(client, token, ip)
    db = SessionLocal()
    try:
        asset = db.query(ServerAsset).filter(ServerAsset.ip_address == ip).first()
        return collect_host_facts(asset, password='plain', private_key=None,
                                  host_key_fingerprint='fp')
    finally:
        db.close()


def test_collect_host_facts_unregistered_key(client, admin_token, monkeypatch):
    """未登记 host key 且不允许未验证 → unavailable_reason 记录 error_type。"""
    from config import settings
    monkeypatch.setattr(settings, 'SSH_ALLOW_UNVERIFIED_HOST_KEY', False)
    with patch('services.host_inspection._open_ssh',
               side_effect=__import__('services.ssh_service', fromlist=['UnknownHostKeyError']).UnknownHostKeyError('10.3.3.2', '未登记')):
        facts = _facts_collect(client, admin_token, '10.3.3.2')
    assert facts.unavailable_reason is not None
    assert any(p.startswith('connect:') for p in facts.probes_failed)


def test_collect_host_facts_probe_failure_isolated(client, admin_token):
    """单个探测失败不拖垮采集，probes_failed 记录。"""
    fake = _fake_ssh()

    real_exec = fake.exec_command

    def broken_exec(cmd, timeout=None):
        if 'ss -tln' in cmd:
            raise Exception('ss not installed')
        return real_exec(cmd, timeout=timeout)

    fake.exec_command = broken_exec
    with patch('services.host_inspection._open_ssh', return_value=fake):
        facts = _facts_collect(client, admin_token, '10.3.3.3')
    assert 'ports' in facts.probes_failed
    assert facts.hostname == 'box.example.com'  # 其余探测仍成功


def test_collect_host_facts_decrypt_error(client, admin_token):
    """非法加密凭据解密失败 → 状态 unknown（直接由 worker 处理，此处验证 collect 不崩）。"""
    from database.models import ServerAsset
    from database.session import SessionLocal
    from services.host_inspection import collect_host_facts

    _create_asset(client, admin_token, '10.3.3.4', pwd='not-encrypted:xxx')
    db = SessionLocal()
    try:
        asset = db.query(ServerAsset).filter(ServerAsset.ip_address == '10.3.3.4').first()
        fake = _fake_ssh()
        with patch('services.host_inspection._open_ssh', return_value=fake):
            facts = collect_host_facts(asset, password=None, private_key=None,
                                       host_key_fingerprint='fp')
    finally:
        db.close()
    assert facts.hostname == 'box.example.com'
