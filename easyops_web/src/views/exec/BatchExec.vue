<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b>受控批量运维（E3）</b>
        <el-tag v-if="!bgLoading" :type="bgEnabled ? 'danger' : 'success'" size="small">
          break-glass: {{ bgEnabled ? '已启用(任意命令)' : '关闭(仅固定操作)' }}
        </el-tag>
      </div>
    </template>

    <el-steps :active="step" align-center finish-status="success" style="margin-bottom:20px">
      <el-step title="选择资产" />
      <el-step title="选择操作" />
      <el-step title="预览确认" />
      <el-step title="执行结果" />
    </el-steps>

    <!-- 第 1 步：资产 -->
    <div v-show="step === 0">
      <el-alert type="info" :closable="false" style="margin-bottom:12px"
        title="批量任务受控执行：先预览确认、有幂等键、并发与超时受限，全部操作进入审计。" />
      <el-select v-model="assetIds" multiple filterable placeholder="选择要执行的主机（最多 50 台）"
        style="width:100%" :multiple-limit="50">
        <el-option v-for="a in assets" :key="a.id" :label="`${a.ip_address} (${a.asset_name})`" :value="a.id" />
      </el-select>
      <div style="margin-top:16px;text-align:right">
        <el-button type="primary" :disabled="assetIds.length === 0" @click="step = 1">
          下一步（已选 {{ assetIds.length }} 台）</el-button>
      </div>
    </div>

    <!-- 第 2 步：操作 -->
    <div v-show="step === 1">
      <el-radio-group v-model="execMode">
        <el-radio-button value="fixed">固定操作目录</el-radio-button>
        <el-radio-button value="break_glass" :disabled="!bgEnabled">任意命令 (break-glass)</el-radio-button>
      </el-radio-group>

      <template v-if="execMode === 'fixed'">
        <el-table :data="operations" highlight-current-row style="margin-top:12px" @current-change="(row) => (selectedOp = row)">
          <el-table-column prop="name" label="操作" width="140" />
          <el-table-column prop="code" label="code" width="140" />
          <el-table-column prop="description" label="说明" />
          <el-table-column label="风险" width="90">
            <template #default="{ row }">
              <el-tag :type="row.risk === 'write' ? 'warning' : 'success'" size="small">
                {{ row.risk === 'write' ? '写(需确认)' : '只读' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <el-form v-if="selectedOp" label-width="140px" style="margin-top:16px;max-width:640px">
          <el-form-item v-for="p in selectedOp.params" :key="p.key" :label="p.label" :required="p.required">
            <el-input v-model="params[p.key]" :placeholder="p.description || `默认 ${p.default}`" />
            <div class="el-form-item__tip" v-if="p.description">{{ p.description }}</div>
          </el-form-item>
          <el-form-item v-if="!selectedOp.params.length" label="参数"><span>无参数</span></el-form-item>
        </el-form>
      </template>

      <template v-else>
        <el-alert type="danger" :closable="false" style="margin:12px 0"
          title="break-glass 任意命令不受参数白名单约束，仅建议在紧急排障时由 admin 开启使用。" />
        <el-input v-model="rawCommand" type="textarea" :rows="3" placeholder="例如：tail -100 /var/log/nginx/error.log"
          style="max-width:640px" />
      </template>

      <div style="margin-top:16px;text-align:right">
        <el-button @click="step = 0">上一步</el-button>
        <el-button type="primary" @click="doPreview" :loading="previewing"
          :disabled="!canBuild">预览</el-button>
      </div>
    </div>

    <!-- 第 3 步：预览与确认 -->
    <div v-show="step === 2">
      <el-descriptions :column="1" border style="margin-bottom:16px">
        <el-descriptions-item label="执行类型">
          <el-tag size="small">{{ preview.risk === 'write' ? '写操作' : '只读操作' }}</el-tag>
          {{ preview.operation ? '固定操作 / ' + preview.operation : 'break-glass 任意命令' }}
        </el-descriptions-item>
        <el-descriptions-item label="目标主机">{{ preview.total_hosts }} 台</el-descriptions-item>
        <el-descriptions-item label="原始命令">
          <code style="word-break:break-all">{{ preview.command }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="主机列表">
          <el-tag v-for="h in preview.hosts" :key="h" size="small" style="margin-right:6px">{{ h }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <el-alert v-if="preview.risk === 'write'" type="warning" :closable="false" style="margin-bottom:12px"
        title="该操作会修改远端状态，必须输入确认令牌并勾选确认后才能执行。" />

      <el-form label-width="140px" style="max-width:560px">
        <el-form-item v-if="preview.risk === 'write'" label="确认令牌">
          <el-input v-model="confirmToken" placeholder="从预览响应复制确认令牌" />
          <el-text type="info" size="small">令牌由 preview 接口在服务端生成，仅本次会话有效。</el-text>
        </el-form-item>
        <el-form-item label="幂等键">
          <el-input v-model="idempotencyKey" placeholder="同一键重复提交不会重复执行">
            <template #append><el-button @click="idempotencyKey = genIdem()">生成</el-button></template>
          </el-input>
        </el-form-item>
      </el-form>

      <div style="text-align:right">
        <el-button @click="step = 1">上一步</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">确认执行</el-button>
      </div>
    </div>

    <!-- 第 4 步：结果 -->
    <div v-show="step === 3">
      <el-descriptions :column="4" border v-if="record" style="margin-bottom:16px">
        <el-descriptions-item label="任务 #{{ record.id }}"><el-tag size="small">{{ record.status }}</el-tag></el-descriptions-item>
        <el-descriptions-item label="成功">{{ record.succeeded }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ record.failed }}</el-descriptions-item>
        <el-descriptions-item label="超时">{{ record.timed_out }}</el-descriptions-item>
      </el-descriptions>

      <el-table :data="hostResults" v-loading="polling" style="margin-bottom:16px">
        <el-table-column prop="host" label="主机" width="160" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="exit_code" label="退出码" width="80" />
        <el-table-column prop="stdout" label="输出" show-overflow-tooltip />
        <el-table-column prop="error" label="错误" show-overflow-tooltip />
      </el-table>

      <div style="text-align:right">
        <el-button @click="step = 2" :disabled="running">上一步</el-button>
        <el-button @click="retryFailed" :disabled="!!record && (record.failed + record.timed_out) === 0" :loading="retrying">
          重试失败主机</el-button>
        <el-button type="primary" @click="reset">新建任务</el-button>
      </div>
    </div>

    <!-- break-glass 管理（admin） -->
    <el-divider content-position="left">break-glass 管理（仅 admin）</el-divider>
    <div style="display:flex;gap:12px;align-items:center">
      <el-switch v-model="bgEnabled" :disabled="bgLoading || !canToggleBg" @change="toggleBg" />
      <el-input v-model="bgReason" placeholder="启用理由（必填，写入审计）" style="max-width:420px" />
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { ElMessage } from 'element-plus';
import {
  getAssetList, getOperations, previewExec, batchExec, getRecordHosts, getRecord,
  retryRecord, getBreakGlass, setBreakGlass,
} from '../../api/exec';

const step = ref(0);
const assets = ref([]);
const assetIds = ref([]);
const operations = ref([]);
const selectedOp = ref(null);
const params = ref({});
const execMode = ref('fixed');
const rawCommand = ref('');
const previewing = ref(false);
const preview = ref({});
const confirmToken = ref('');
const idempotencyKey = ref('');
const submitting = ref(false);
const record = ref(null);
const hostResults = ref([]);
const polling = ref(false);
const retrying = ref(false);
const bgEnabled = ref(false);
const bgLoading = ref(true);
const bgReason = ref('');
let timer = null;

const canBuild = computed(() => {
  if (execMode.value === 'break_glass') return rawCommand.value.trim().length > 0;
  if (!selectedOp.value) return false;
  return selectedOp.value.params.every((p) => !p.required || (params.value[p.key] ?? '') !== '');
});

const canSubmit = computed(() => {
  if (!preview.value.risk) return false;
  if (preview.value.risk === 'write' && !confirmToken.value) return false;
  return idempotencyKey.value.trim().length > 0;
});

const running = computed(() => record.value && ['running', 'partial'].includes(record.value.status));

function genIdem() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function statusType(s) {
  return { queued: 'info', running: 'primary', succeeded: 'success', failed: 'danger', timed_out: 'warning' }[s] || 'info';
}

async function loadAssets() {
  try { assets.value = (await getAssetList()).data; } catch (e) { ElMessage.error('加载资产失败'); }
}

async function loadOperations() {
  try { operations.value = (await getOperations()).data; } catch (e) { ElMessage.error('加载操作目录失败'); }
}

async function loadBg() {
  try {
    bgEnabled.value = (await getBreakGlass()).data.enabled;
  } catch (e) { /* noop */ } finally { bgLoading.value = false; }
}

async function toggleBg() {
  if (bgEnabled.value && !bgReason.value.trim()) {
    ElMessage.warning('启用 break-glass 必须填写理由');
    bgEnabled.value = false;
    return;
  }
  try {
    await setBreakGlass({ enabled: bgEnabled.value, reason: bgReason.value });
    ElMessage.success(bgEnabled.value ? 'break-glass 已启用' : 'break-glass 已关闭');
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '切换失败（可能不是 admin）');
    bgEnabled.value = !bgEnabled.value;
  }
}

async function doPreview() {
  previewing.value = true;
  try {
    const data = execMode.value === 'fixed'
      ? { asset_ids: assetIds.value, operation: selectedOp.value.code, params: params.value }
      : { asset_ids: assetIds.value, command: rawCommand.value };
    preview.value = (await previewExec(data)).data;
    idempotencyKey.value = genIdem();
    step.value = 2;
    if (!preview.value.risk || preview.value.risk !== 'write') confirmToken.value = '';
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '预览失败');
  } finally { previewing.value = false; }
}

async function submit() {
  submitting.value = true;
  try {
    const data = {
      asset_ids: assetIds.value,
      idempotency_key: idempotencyKey.value,
    };
    if (execMode.value === 'fixed') { data.operation = selectedOp.value.code; data.params = params.value; }
    else data.command = rawCommand.value;
    if (preview.value.risk === 'write') data.confirm_token = confirmToken.value;
    record.value = (await batchExec(data)).data;
    step.value = 3;
    await loadHosts();
    startPolling();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败');
  } finally { submitting.value = false; }
}

async function loadHosts() {
  if (!record.value) return;
  polling.value = true;
  try { hostResults.value = (await getRecordHosts(record.value.id)).data; } finally { polling.value = false; }
}

async function poll() {
  if (!record.value) return;
  try {
    const r = (await getRecord(record.value.id)).data;
    record.value = { ...record.value, ...r };
    await loadHosts();
    if (!['running', 'partial'].includes(r.status)) stopPolling();
  } catch (e) { /* transient */ }
}

function startPolling() { stopPolling(); timer = setInterval(poll, 1500); }
function stopPolling() { if (timer) { clearInterval(timer); timer = null; } }

async function retryFailed() {
  if (!record.value) return;
  retrying.value = true;
  try {
    await retryRecord(record.value.id);
    ElMessage.success('已重新排队失败主机');
    startPolling();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '重试失败'); } finally { retrying.value = false; }
}

function reset() {
  stopPolling();
  step.value = 0; assetIds.value = []; selectedOp.value = null; params.value = {};
  rawCommand.value = ''; preview.value = {}; confirmToken.value = ''; idempotencyKey.value = '';
  record.value = null; hostResults.value = [];
}

onMounted(() => { loadAssets(); loadOperations(); loadBg(); });
onUnmounted(stopPolling);
</script>