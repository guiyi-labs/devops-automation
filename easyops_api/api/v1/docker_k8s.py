from fastapi import APIRouter
router = APIRouter()
@router.get('/docker/containers')
def docker_containers():
    try:
        import docker; c = docker.from_env()
        return [{'id': x.short_id, 'name': x.name, 'status': x.status} for x in c.containers.list(all=True)]
    except Exception as exc: return [{'error': str(exc)}]
@router.get('/k8s/pods')
def k8s_pods(namespace: str = 'default'):
    try:
        from kubernetes import client, config; config.load_incluster_config(); pods = client.CoreV1Api().list_namespaced_pod(namespace)
        return [{'name': p.metadata.name, 'phase': p.status.phase, 'namespace': namespace} for p in pods.items]
    except Exception as exc: return [{'error': str(exc)}]
