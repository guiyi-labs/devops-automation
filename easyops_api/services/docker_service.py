def list_docker_containers():
    import docker
    client = docker.from_env()
    return [{'id': c.short_id, 'name': c.name, 'status': c.status} for c in client.containers.list(all=True)]
