import http from './http';export const loginApi=d=>http.post('/user/login',d);export const initAdminApi=()=>http.post('/user/init-admin')
