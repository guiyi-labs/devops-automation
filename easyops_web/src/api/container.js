import http from './http';export const listContainers=()=>http.get('/container/docker/containers');export const listPods=()=>http.get('/container/k8s/pods')
