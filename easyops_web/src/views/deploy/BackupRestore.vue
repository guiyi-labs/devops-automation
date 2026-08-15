<template>
  <el-card>
    <template #header><b>备份与恢复（E5）</b></template>

    <el-alert type="info" :closable="false" style="margin-bottom:12px"
      title="保留策略：失败备份不覆盖最后一份有效备份；仅校验（sha256 + 一致性）通过的备份可恢复。" />

    <el-form :inline="true">
      <el-form-item label="数据库"><el-input v-model="dbName" style="width:160px" placeholder="easyops" /></el-form-item>
      <el-form-item><el-button type="primary" :loading="backing" @click="doBackup">立即备份</el-button></el-form-item>
    </el-form>

    <el-table :data="records" v-loading="loading">
      <el-table-column prop="id" label="#" width="60" />
      <el-table-column prop="op_type" label="类型" width="90" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="database" label="数据库" width="110" />
      <el-table-column prop="file_size_bytes" label="大小(B)" width="110" />
      <el-table-column label="校验" width="110">
        <template #default="{ row }">
          <el-tag :type="row.checksum_ok ? 'success' : 'info'" size="small">{{ row.checksum_ok ? '通过' : '—' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="exec_user" label="执行人" width="90" />
      <el-table-column label="校验摘要" min-width="220">
        <template #default="{ row }">
          <el-text v-if="row.checksum" size="small" type="info">{{ shortChecksum(row.checksum) }}</el-text>
          <el-text v-else size="small">—</el-text>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button v-if="row.op_type === 'backup' && row.status === 'succeeded'"
            size="small" type="primary" link @click="doRestore(row)">恢复</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showVal" title="一致性校验详情" width="640">
      <pre style="white-space:pre-wrap;font-family:monospace;font-size:13px">{{ validationText }}</pre>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { createBackup, restoreBackup, listBackupRecords } from '../../api/deploy';

const records = ref([]);
const loading = ref(false);
const backing = ref(false);
const dbName = ref('easyops');
const showVal = ref(false);
const validationText = ref('');

function statusType(s) {
  return { succeeded: 'success', failed: 'danger', running: 'primary' }[s] || 'info';
}
function shortChecksum(c) { return c.length > 16 ? c.slice(0, 16) + '…' : c; }

async function load() {
  loading.value = true;
  try { records.value = (await listBackupRecords()).data; } finally { loading.value = false; }
}
async function doBackup() {
  backing.value = true;
  try {
    await createBackup({ database: dbName.value });
    ElMessage.success('备份任务已触发');
    setTimeout(load, 1200);
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '备份失败'); } finally { backing.value = false; }
}
async function doRestore(row) {
  try {
    await ElMessageBox.confirm(`确认从备份 #${row.id} 恢复？恢复前建议先备份当前数据。`, '恢复确认');
    const { data } = await restoreBackup({ backup_id: row.id });
    ElMessage.success(`恢复任务 #${data.id} 已触发`);
    if (data.validation) { validationText.value = data.validation; showVal.value = true; }
    setTimeout(load, 1500);
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '恢复失败'); }
}

onMounted(load);
</script>