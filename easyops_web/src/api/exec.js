import http from './http';export const getAssetList=()=>http.get('/asset/');export const batchExecApi=d=>http.post('/exec/batch',d)
