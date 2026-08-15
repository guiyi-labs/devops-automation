import http from './http';

// E4 主机巡检
export const collectInspection = (assetIds) => http.post('/inspection/collect', { asset_ids: assetIds });
export const getInspectionRecords = () => http.get('/inspection/records');
export const getInspectionRecord = (id) => http.get(`/inspection/records/${id}`);
export const getInspectionHosts = (id) => http.get(`/inspection/records/${id}/hosts`);
export const getAssetLatestInspection = (assetId) => http.get(`/inspection/assets/${assetId}/latest`);
export const getInspectionRules = () => http.get('/inspection/rules');
export const createInspectionRule = (data) => http.post('/inspection/rules', data);
export const updateInspectionRule = (id, data) => http.put(`/inspection/rules/${id}`, data);
export const deleteInspectionRule = (id) => http.delete(`/inspection/rules/${id}`);