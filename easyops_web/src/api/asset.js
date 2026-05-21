import http from './http';export const getAssetList=()=>http.get('/asset/');export const createAsset=d=>http.post('/asset/',d)
