<template>
  <el-card>
    <template #header><b>主机巡检与监控（E4）</b></template>

    <el-tabs v-model="tab">
      <el-tab-pane label="巡检采集" name="collect">
        <el-form :inline="true" style="margin-bottom:12px">
          <el-form-item label="选择主机">
            <el-select v-model="assetIds" multiple filterable placeholder="选择要巡检的主机（最多 50 台）"
              style="width:400px" :multiple-limit="50">
              <el-option v-for="a in assets" :key="a.id" :label="`${a.ip_address} (${a.asset_name})`" :value="a.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :disabled="assetIds.length === 0" :loading="collecting" @click="collect">
              开始巡检</el-button>
          </el-form-item>
        </el-form>
        <el-alert type="info" :closable="false" title="巡检为逐主机只读 SSH 采集，采集结果带 observed_at 时间戳；缺数据固定为 unknown，不误判为健康。" />

        <el-table :data="records" style="margin-top:16px" @row-click="openRecord" :row-class-name="rowClass">
          <el-table-column prop="id" label="#" width="60" />
          <el-table-column prop="exec_user" label="执行人" width="110" />
          <el-table-column prop="total_hosts" label="主机数" width="90" />
          <el-table-column label="健康" width="120">
            <template #default="{ row }">
              <el-tag type="success" size="small">{{ row.succeeded }}</el-tag>
              <el-tag type="info" size="small" style="margin-left:4px">unknown {{ row.unknown }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90">
            <template #default="{ row }"><el-tag :type="row.status === 'done' ? 'success' : 'primary'" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column label="采集时间" width="170">
            <template #default="{ row }">{{ fmt(row.create_time) }}</template>
          </el-table-column>
          <el-table-column label="查看" width="90">
            <template #default="{ row }"><el-button size="small" link type="primary" @click="openRecord(row)">详情</el-button></template>
          </el-table-column>
        </el-table>

        <el-dialog v-model="showDetail" :title="`巡检详情 #${active?.id || ''}`" width="900">
          <el-table :data="hosts" v-loading="loadingHosts" size="small">
            <el-table-column prop="host" label="主机" width="160" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag :type="statusType(row.overall_status)" size="small">{{ row.overall_status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="事实快照" min-width="300">
              <template #default="{ row }">
                <div v-if="row.facts">
                  <div v-if="row.overall_status !== 'unknown'">
                    磁盘最大 {{ maxDisk(row.facts) }}%，内存 {{ json(row.facts)?.memory_used_pct }}%，load5 {{ json(row.facts)?.load_5 }}
                  </div>
                  <el-text v-else type="info" size="small">{{ row.unavailable_reason }}</el-text>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="规则明细" min-width="240">
              <template #default="{ row }">
                <el-tooltip v-if="jsonArr(row.rule_results)?.length" :content="fmtRules(row.rule_results)">
                  <el-button size="small" link>查看规则</el-button>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top:12px;text-align:right">
            <span style="margin-right:16px;color:#909399">采集时间 {{ active ? fmt(active.create_time) : '' }}</span>
            <el-button @click="showDetail = false">关闭</el-button>
          </div>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane label="巡检规则" name="rules">
        <el-button type="primary" size="small" style="margin-bottom:12px" @click="openNewRule">新增规则</el-button>
        <el-table :data="rules" size="small">
          <el-table-column prop="name" label="名称" width="160" />
          <el-table-column prop="metric" label="指标" width="150" />
          <el-table-column prop="operator" label="操作符" width="90" />
          <el-table-column prop="threshold" label="阈值" width="90" />
          <el-table-column label="严重度" width="100">
            <template #default="{ row }"><el-tag :type="row.severity === 'critical' ? 'danger' : 'warning'" size="small">{{ row.severity }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="enabled" label="启用" width="80">
            <template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="editRule(row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="removeRule(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-dialog v-model="showRule" :title="editingId ? '编辑规则' : '新增规则'" width="520">
          <el-form label-width="110px">
            <el-form-item label="名称"><el-input v-model="ruleForm.name" /></el-form-item>
            <el-form-item label="指标">
              <el-select v-model="ruleForm.metric" style="width:100%">
                <el-option v-for="m in metrics" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="操作符">
              <el-select v-model="ruleForm.operator" style="width:100%">
                <el-option v-for="o in operators" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="阈值"><el-input v-model="ruleForm.threshold" placeholder="例如 90 / 4 / nginx / 8080" /></el-form-item>
            <el-form-item label="严重度">
              <el-select v-model="ruleForm.severity" style="width:100%">
                <el-option label="warning" value="warning" /><el-option label="critical" value="critical" />
              </el-select>
            </el-form-item>
            <el-form-item label="描述"><el-input v-model="ruleForm.description" /></el-form-item>
          </el-form>
          <div style="text-align:right">
            <el-button @click="showRule = false">取消</el-button>
            <el-button type="primary" @click="saveRule">保存</el-button>
          </div>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { getAssetList } from '../../api/asset';
import {
  collectInspection, getInspectionRecords, getInspectionHosts,
  getInspectionRules, createInspectionRule, updateInspectionRule, deleteInspectionRule,
} from '../../api/inspection';

const tab = ref('collect');
const assets = ref([]);
const assetIds = ref([]);
const collecting = ref(false);
const records = ref([]);
const active = ref(null);
const hosts = ref([]);
const loadingHosts = ref(false);
const showDetail = ref(false);

const rules = ref([]);
const showRule = ref(false);
const editingId = ref(null);
const ruleForm = reactive({ name: '', metric: 'disk_used_pct', operator: 'gt', threshold: '90', severity: 'warning', description: '' });
const metrics = [
  { value: 'disk_used_pct', label: '磁盘使用率 %' },
  { value: 'inode_used_pct', label: 'inode 使用率 %' },
  { value: 'memory_used_pct', label: '内存使用率 %' },
  { value: 'swap_used_pct', label: 'swap 使用率 %' },
  { value: 'load_5', label: '5 分钟负载' },
  { value: 'service_stopped', label: '服务停止（阈值=服务名）' },
  { value: 'port_not_listening', label: '端口未监听（阈值=端口）' },
];
const operators = [
  { value: 'gt', label: '>' }, { value: 'lt', label: '<' },
  { value: 'eq', label: '=' }, { value: 'ne', label: '≠' },
  { value: 'contains', label: '包含' }, { value: 'not_contains', label: '不包含' },
];

function fmt(v) { return v ? String(v).replace('T', ' ').slice(0, 19) : ''; }
function json(s) { try { return JSON.parse(s); } catch (e) { return null; } }
function jsonArr(s) { const v = json(s); return Array.isArray(v) ? v : []; }
function maxDisk(facts) {
  const d = json(facts)?.disks || [];
  const pcts = d.map((x) => x.used_pct).filter((x) => x != null);
  return pcts.length ? Math.max(...pcts) : '-';
}
function statusType(s) {
  return { healthy: 'success', warning: 'warning', critical: 'danger', unknown: 'info' }[s] || 'info';
}
function rowClass({ row }) { return row.status === 'done' ? '' : 'el-table__row-warning'; }
function fmtRules(s) {
  const arr = jsonArr(s);
  return arr.map((r) => `${r.rule}: ${r.status}`).join('\n');
}

async function loadAssets() { try { assets.value = (await getAssetList()).data; } catch (e) { /* noop */ } }
async function loadRecords() {
  try { records.value = (await getInspectionRecords()).data; } catch (e) { ElMessage.error('加载巡检记录失败'); }
}
async function collect() {
  collecting.value = true;
  try {
    const { data } = await collectInspection(assetIds.value);
    ElMessage.success(`已触发巡检任务 #${data.record_id}（${data.total_hosts} 台主机）`);
    assetIds.value = [];
    setTimeout(loadRecords, 1500);
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '触发巡检失败'); } finally { collecting.value = false; }
}
async function openRecord(row) {
  active.value = row;
  showDetail.value = true;
  loadingHosts.value = true;
  try { hosts.value = (await getInspectionHosts(row.id)).data; } finally { loadingHosts.value = false; }
}

async function loadRules() { try { rules.value = (await getInspectionRules()).data; } catch (e) { /* noop */ } }
function openNewRule() {
  editingId.value = null;
  Object.assign(ruleForm, { name: '', metric: 'disk_used_pct', operator: 'gt', threshold: '90', severity: 'warning', description: '' });
  showRule.value = true;
}
function editRule(row) {
  editingId.value = row.id;
  Object.assign(ruleForm, { name: row.name, metric: row.metric, operator: row.operator, threshold: row.threshold, severity: row.severity, description: row.description });
  showRule.value = true;
}
async function saveRule() {
  try {
    if (editingId.value) await updateInspectionRule(editingId.value, ruleForm);
    else await createInspectionRule(ruleForm);
    ElMessage.success('已保存');
    showRule.value = false;
    loadRules();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '保存失败'); }
}
async function removeRule(row) {
  try {
    await ElMessageBox.confirm(`确认删除规则「${row.name}」？`, '删除规则');
    await deleteInspectionRule(row.id);
    loadRules();
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败'); }
}

onMounted(() => { loadAssets(); loadRecords(); if (tab.value === 'rules') loadRules(); });
</script>