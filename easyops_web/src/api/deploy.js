import http from './http';

// E5 受控部署
export const listProjects = () => http.get('/deploy/projects');
export const createProject = (d) => http.post('/deploy/projects', d);
export const previewDeploy = (id, d) => http.post(`/deploy/projects/${id}/preview`, d || {});
export const createRelease = (d) => http.post('/deploy/releases', d);
export const listReleases = (projectId) => http.get(`/deploy/projects/${projectId}/releases`);
export const getRelease = (id) => http.get(`/deploy/releases/${id}`);
export const rollbackRelease = (id) => http.post(`/deploy/releases/${id}/rollback`);
export const listTemplates = () => http.get('/deploy/templates');

// E5 备份恢复
export const createBackup = (d) => http.post('/backup/create', d || {});
export const restoreBackup = (d) => http.post('/backup/restore', d);
export const listBackupRecords = () => http.get('/backup/records');
export const getBackupRecord = (id) => http.get(`/backup/records/${id}`);
export const getBackupPolicy = () => http.get('/backup/policy');