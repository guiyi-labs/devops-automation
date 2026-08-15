<template>
  <el-card>
    <template #header><b>受控部署计划（E5）</b></template>

    <el-form :inline="true">
      <el-form-item label="项目名"><el-input v-model="projForm.project_name" style="width:180px" /></el-form-item>
      <el-form-item label="Git 仓库"><el-input v-model="projForm.git_url" style="width:320px" placeholder="https://github.com/org/repo.git" /></el-form-item>
      <el-form-item label="环境"><el-input v-model="projForm.env_type" style="width:100px" placeholder="dev" /></el-form-item>
      <el-form-item><el-button type="primary" @click="doCreate">登记项目</el-button></el-form-item>
    </el-form>

    <el-table :data="projects" style="margin-top:12px">
      <el-table-column prop="project_name" label="项目" width="160" />
      <el-table-column prop="git_url" label="仓库" min-width="240" />
      <el-table-column prop="git_branch" label="分支" width="90" />
      <el-table-column prop="env_type" label="环境" width="90" />
      <el-table-column label="操作" width="260">
        <template #default="{ row }">
          <el-button size="small" @click="openPreview(row)">部署预览</el-button>
          <el-button size="small" type="primary" @click="showReleases(row)">发布记录</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showPreview" title="部署计划预览" width="720">
      <el-form label-width="90px">
        <el-form-item label="镜像"><el-input v-model="previewForm.image" placeholder="easyops/项目名" /></el-form-item>
        <el-form-item label="版本"><el-input v-model="previewForm.version" placeholder="latest" style="width:160px" /></el-form-item>
        <el-form-item label="端口"><el-input v-model.number="previewForm.port" placeholder="8080" style="width:160px" /></el-form-item>
      </el-form>
      <el-button type="primary" @click="doPreview">生成预览</el-button>
      <div v-if="plan" style="margin-top:12px">
        <el-alert type="info" :closable="false" style="margin-bottom:8px"
          title="受控步骤：只执行模板内固定动作，不执行项目仓库任意脚本。" />
        <el-tag v-for="s in plan.steps" :key="s" style="margin-right:6px">{{ s }}</el-tag>
        <div style="margin-top:10px;color:#606266">image={{ plan.image }} version={{ plan.version }} port={{ plan.port }}</div>
        <div v-if="rollbackPoint" style="margin-top:6px;color:#e6a23c">
          回滚点：release #{{ rollbackPoint.id }}（{{ rollbackPoint.image }}:{{ rollbackPoint.version }}）
        </div>
        <el-button type="primary" style="margin-top:12px" :loading="deploying" @click="doDeploy">确认发布</el-button>
      </div>
    </el-dialog>

    <el-dialog v-model="showRel" :title="`发布记录：${activeProject?.project_name || ''}`" width="860">
      <el-table :data="releases" size="small" v-loading="loadingRel">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="release_type" label="类型" width="90" />
        <el-table-column label="状态" width="140">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="image" label="镜像" min-width="180" />
        <el-table-column prop="version" label="版本" width="90" />
        <el-table-column prop="exec_user" label="执行人" width="90" />
        <el-table-column label="结果" min-width="160">
          <template #default="{ row }">
            <el-tooltip v-if="row.result" :content="prettyResult(row.result)">
              <el-button size="small" link>查看</el-button>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button v-if="row.status === 'succeeded'" size="small" type="danger" link @click="doRollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-button style="margin-top:10px" type="primary" size="small" @click="openPreview(activeProject)">新部署</el-button>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { listProjects, createProject, previewDeploy, createRelease, listReleases, rollbackRelease } from '../../api/deploy';

const projects = ref([]);
const projForm = reactive({ project_name: '', git_url: '', env_type: 'dev' });
const showPreview = ref(false);
const previewForm = reactive({ image: '', version: 'latest', port: 8080 });
const plan = ref(null);
const rollbackPoint = ref(null);
const deploying = ref(false);
const activeProject = ref(null);
const showRel = ref(false);
const releases = ref([]);
const loadingRel = ref(false);

function statusType(s) {
  return { succeeded: 'success', failed: 'danger', running: 'primary', requested: 'info', rollback_succeeded: 'success', rollback_failed: 'danger' }[s] || 'info';
}
function prettyResult(r) {
  try { return JSON.stringify(JSON.parse(r), null, 1); } catch (e) { return r; }
}

async function load() { try { projects.value = (await listProjects()).data; } catch (e) { /* noop */ } }
async function doCreate() {
  if (!projForm.project_name || !projForm.git_url) { ElMessage.warning('项目名与仓库必填'); return; }
  try { await createProject(projForm); ElMessage.success('已登记'); projForm.project_name = ''; projForm.git_url = ''; load(); }
  catch (e) { ElMessage.error(e?.response?.data?.detail || '登记失败'); }
}
function openPreview(row) {
  activeProject.value = row;
  plan.value = null;
  rollbackPoint.value = null;
  showPreview.value = true;
}
async function doPreview() {
  try {
    const { data } = await previewDeploy(activeProject.value.id, {
      image: previewForm.image || undefined,
      version: previewForm.version, port: previewForm.port,
    });
    plan.value = data.plan;
    rollbackPoint.value = data.rollback_point;
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '预览失败'); }
}
async function doDeploy() {
  deploying.value = true;
  try {
    const { data } = await createRelease({
      project_id: activeProject.value.id,
      image: plan.value.image, version: plan.value.version, port: plan.value.port,
    });
    ElMessage.success(`已发布 release #${data.release_id}`);
    plan.value = null;
    showPreview.value = false;
    if (showRel.value) showReleases(activeProject.value);
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '发布失败'); } finally { deploying.value = false; }
}
async function showReleases(row) {
  activeProject.value = row;
  showRel.value = true;
  loadingRel.value = true;
  try { releases.value = (await listReleases(row.id)).data; } finally { loadingRel.value = false; }
}
async function doRollback(row) {
  try {
    await ElMessageBox.confirm(`确认回滚 release #${row.id}？将恢复到最近一次成功发布。`, '回滚确认');
    const { data } = await rollbackRelease(row.id);
    ElMessage.success(`回滚任务 #${data.rollback_id} 已触发`);
    showReleases(activeProject.value);
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '回滚失败'); }
}

onMounted(load);
</script>