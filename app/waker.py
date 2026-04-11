import logging
from datetime import datetime, timezone

from kubernetes import client, config

log = logging.getLogger(__name__)

# Track recently woken deployments to avoid spamming the API
_recently_woken: dict[str, datetime] = {}
COOLDOWN_SECONDS = 30

try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

apps_v1 = client.AppsV1Api()


def wake_deployment(name: str, namespace: str) -> dict:
    """Scale a deployment to 1 replica and set a timestamp annotation."""
    key = f"{namespace}/{name}"
    now = datetime.now(timezone.utc)

    # Cooldown: don't re-patch if we just woke this deployment
    if key in _recently_woken:
        elapsed = (now - _recently_woken[key]).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            log.info("Skipping wake for %s (woken %.0fs ago)", key, elapsed)
            return {
                "status": "waking",
                "message": f"{name} is already waking up, please wait...",
            }

    try:
        deployment = apps_v1.read_namespaced_deployment(name, namespace)
    except client.ApiException as e:
        if e.status == 404:
            log.warning("Deployment %s not found in namespace %s", name, namespace)
            return {
                "status": "error",
                "message": f"Deployment {name} not found.",
            }
        raise

    current_replicas = deployment.spec.replicas or 0

    if current_replicas > 0:
        # Already scaled up — might be starting
        ready = (deployment.status.ready_replicas or 0) > 0
        if ready:
            return {
                "status": "ready",
                "message": f"{name} is ready! Refreshing...",
            }
        return {
            "status": "waking",
            "message": f"{name} is starting up, please wait...",
        }

    # Scale up: patch replicas to 1 and set timestamp annotation for kube-downscaler grace period
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    patch = {
        "spec": {"replicas": 1},
        "metadata": {
            "annotations": {
                "downscaler/last-wakeup": timestamp,
            }
        },
    }

    try:
        apps_v1.patch_namespaced_deployment(name, namespace, patch)
        _recently_woken[key] = now
        log.info("Scaled up %s to 1 replica (timestamp: %s)", key, timestamp)
        return {
            "status": "waking",
            "message": f"Waking up {name}... This usually takes 15-60 seconds.",
        }
    except client.ApiException as e:
        log.error("Failed to patch deployment %s: %s", key, e)
        return {
            "status": "error",
            "message": f"Failed to wake {name}: {e.reason}",
        }
