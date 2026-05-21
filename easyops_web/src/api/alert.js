import http from './http';export const listRules=()=>http.get('/alert/rules');export const createRule=d=>http.post('/alert/rules',d)
