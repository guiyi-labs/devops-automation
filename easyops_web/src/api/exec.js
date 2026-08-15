import http from './http';

// 资产
export const getAssetList = () => http.get('/asset/');

// E3 受控批量运维
export const getOperations = () => http.get('/exec/operations');
export const previewExec = (data) => http.post('/exec/preview', data);
export const batchExec = (data) => http.post('/exec/batch', data);
export const getRecords = () => http.get('/exec/records');
export const getRecord = (id) => http.get(`/exec/records/${id}`);
export const getRecordHosts = (id) => http.get(`/exec/records/${id}/hosts`);
export const retryRecord = (id) => http.post(`/exec/records/${id}/retry`);
export const getBreakGlass = () => http.get('/exec/break_glass');
export const setBreakGlass = (data) => http.post('/exec/break_glass', data);