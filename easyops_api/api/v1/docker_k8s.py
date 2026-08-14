from fastapi import APIRouter, Depends

from database.models import SysUser
from dependencies import get_current_user

router = APIRouter()


@router.get('/docker/containers')
def docker_containers(user: SysUser = Depends(get_current_user)):
    try:
        import docker
        c = docker.from_env()
        return [{'id': x.short_id, 'name': x.name, 'status': x.status} for x in c.containers.list(all=True)]
    except Exception as exc:
        from common.redact import redact
        return [{'error': redact(str(exc))}]


@router.get('/k8s/pods')
def k8s_pods(namespace: str = 'default', user: SysUser = Depends(get_current_user)):
    try:
        from kubernetes import client, config
        config.load_incluster_config()
        pods = client.CoreV1Api().list_namespaced_pod(namespace)
        return [{'name': p.metadata.name, 'phase': p.status.phase, 'namespace': namespace} for p in pods.items]
    except Exception as exc:
        from common.redact import redact
        return [{'error': redact(str(exc))}]