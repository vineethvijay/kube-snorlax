import logging
import os

from flask import Flask, render_template, request

from app.waker import wake_deployment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

NAMESPACE = os.environ.get("TARGET_NAMESPACE", "default")


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def handle_wake(path):
    """Handle 503 errors forwarded by NGINX ingress via custom-http-errors.

    NGINX sends these headers when forwarding to the default backend:
    - X-Original-URI: the original request path
    - X-Service-Name: the backend service name that was unavailable
    - X-Service-Port: the backend service port
    - X-Namespace: the namespace of the backend service
    - X-Ingress-Name: the ingress resource name
    - X-Code: the original HTTP status code (503)
    """
    original_uri = request.headers.get("X-Original-URI", "/")
    service_name = request.headers.get("X-Service-Name", "")
    namespace = request.headers.get("X-Namespace", NAMESPACE)
    ingress_name = request.headers.get("X-Ingress-Name", "")
    code = request.headers.get("X-Code", "503")

    # If no service name header, this is a direct hit (not a 503 forward)
    if not service_name:
        return "kube-snorlax is running. Nothing to wake.", 200

    # Convention: deployment name == service name
    deployment_name = service_name

    log.info(
        "Wake request: service=%s namespace=%s ingress=%s uri=%s code=%s",
        service_name,
        namespace,
        ingress_name,
        original_uri,
        code,
    )

    result = wake_deployment(deployment_name, namespace)

    return render_template(
        "waking.html",
        service_name=service_name,
        deployment_name=deployment_name,
        namespace=namespace,
        original_uri=original_uri,
        status=result["status"],
        message=result["message"],
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
