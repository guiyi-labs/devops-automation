def list_pods(namespace: str = 'default'):
    from kubernetes import client, config
    config.load_incluster_config()
    pods = client.CoreV1Api().list_namespaced_pod(namespace)
    return [{'name': p.metadata.name, 'phase': p.status.phase, 'namespace': namespace} for p in pods.items]
