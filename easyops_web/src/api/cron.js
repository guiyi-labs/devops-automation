import http from './http';export const listCronTasks=()=>http.get('/cron/tasks');export const createCronTask=d=>http.post('/cron/tasks',d)
