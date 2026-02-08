"""
Kubernetes implementation of container orchestration.
"""

import logging
import time
from typing import Any

from broker.config.loader import BrokerConfig
from broker.domain.orchestrator.base import ContainerInfo

logger = logging.getLogger("session-broker")

# Kubernetes client is optional - only imported when backend is kubernetes
try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException

    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    client = None
    config = None
    ApiException = Exception


class KubernetesOrchestrator:
    """Kubernetes-based container orchestrator."""

    def __init__(self):
        """Initialize Kubernetes client."""
        if not KUBERNETES_AVAILABLE:
            raise RuntimeError(
                "kubernetes package not installed. "
                "Install with: pip install kubernetes>=28.1.0"
            )

        # Load config - try in-cluster first, then kubeconfig
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except config.ConfigException:
            try:
                config.load_kube_config()
                logger.info("Loaded kubeconfig")
            except config.ConfigException as e:
                raise RuntimeError(f"Could not load Kubernetes config: {e}")

        self._core_api = client.CoreV1Api()
        self._k8s_config = BrokerConfig.get("orchestrator", "kubernetes", default={})
        self._namespace = self._k8s_config.get("namespace", "guacamole")

    def _get_pod_spec(
        self, session_id: str, username: str | None, vnc_password: str
    ) -> dict[str, Any]:
        """
        Build Pod specification for VNC session.

        Args:
            session_id: Session identifier
            username: Username (None for pool containers)
            vnc_password: VNC password

        Returns:
            Pod specification dict
        """
        container_config = BrokerConfig.get("containers", default={})
        vnc_image = container_config.get("image", "vnc-browser:latest")

        # For pool containers (no username), use default config
        homepage = "about:blank"
        if username:
            # Import here to avoid circular imports
            from broker.domain.user_profile import UserProfile

            # Get user configuration
            user_config = UserProfile.get_config(username)
            homepage = user_config.get("homepage", "about:blank")
            bookmarks = user_config.get("bookmarks", [])
            autofill = user_config.get("autofill", [])

            # Apply browser policies
            browser = BrokerConfig.get_browser_type()
            UserProfile.set_browser_policies(username, bookmarks, homepage, autofill)
            logger.info(
                f"Applied {browser} policies for {username}: "
                f"{len(bookmarks)} bookmarks, homepage={homepage}"
            )

        # Get Kubernetes-specific config
        k8s_labels = self._k8s_config.get("labels", {})
        image_pull_policy = self._k8s_config.get("image_pull_policy", "IfNotPresent")
        image_pull_secrets = self._k8s_config.get("image_pull_secrets", [])
        node_selector = self._k8s_config.get("node_selector", {})
        tolerations = self._k8s_config.get("tolerations", [])
        resources = self._k8s_config.get("resources", {})
        security_context = self._k8s_config.get("security_context", {})

        # Build labels
        labels = {
            "guac.managed": "true",
            "guac.session.id": session_id,
            "guac.pool": "true" if not username else "false",
            **k8s_labels,
        }
        if username:
            labels["guac.username"] = username

        # Build container spec
        env_vars = [
            {"name": "VNC_PW", "value": vnc_password},
            {"name": "VNC_RESOLUTION", "value": "1920x1080"},
            {"name": "VNC_COL_DEPTH", "value": "24"},
            {"name": "STARTING_URL", "value": homepage},
        ]
        if username:
            env_vars.append({"name": "GUAC_USERNAME", "value": username})

        container_spec = {
            "name": "vnc",
            "image": vnc_image,
            "imagePullPolicy": image_pull_policy,
            "env": env_vars,
            "ports": [{"containerPort": 5900, "name": "vnc", "protocol": "TCP"}],
        }

        # Add resources if specified
        if resources:
            container_spec["resources"] = {}
            if "requests" in resources:
                container_spec["resources"]["requests"] = resources["requests"]
            if "limits" in resources:
                container_spec["resources"]["limits"] = resources["limits"]

        # Add security context to container if specified
        if security_context:
            container_spec["securityContext"] = {}
            if "run_as_non_root" in security_context:
                container_spec["securityContext"]["runAsNonRoot"] = security_context[
                    "run_as_non_root"
                ]
            if "run_as_user" in security_context:
                container_spec["securityContext"]["runAsUser"] = security_context[
                    "run_as_user"
                ]

        # Build pod spec
        pod_spec = {
            "containers": [container_spec],
            "restartPolicy": "Never",
        }

        # Add optional pod spec fields
        if node_selector:
            pod_spec["nodeSelector"] = node_selector

        if tolerations:
            pod_spec["tolerations"] = tolerations

        if image_pull_secrets:
            pod_spec["imagePullSecrets"] = [
                {"name": secret} for secret in image_pull_secrets
            ]

        service_account = self._k8s_config.get("service_account")
        if service_account:
            pod_spec["serviceAccountName"] = service_account

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"vnc-{session_id}",
                "namespace": self._namespace,
                "labels": labels,
            },
            "spec": pod_spec,
        }

    def _wait_for_pod_ip(self, pod_name: str, timeout: int = 60) -> str:
        """
        Wait for a Pod to get an IP address.

        Args:
            pod_name: Name of the pod
            timeout: Timeout in seconds

        Returns:
            Pod IP address

        Raises:
            TimeoutError: If pod doesn't get IP within timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            try:
                pod = self._core_api.read_namespaced_pod(
                    name=pod_name, namespace=self._namespace
                )
                if pod.status.pod_ip:
                    return pod.status.pod_ip
            except ApiException as e:
                logger.warning(f"Error reading pod {pod_name}: {e}")
            time.sleep(1)

        raise TimeoutError(f"Pod {pod_name} did not get IP within {timeout}s")

    def spawn_container(
        self, session_id: str, username: str, vnc_password: str
    ) -> ContainerInfo:
        """
        Spawn a VNC Pod.

        Args:
            session_id: Session identifier
            username: Username
            vnc_password: VNC password

        Returns:
            ContainerInfo with pod details
        """
        pod_name = f"vnc-{session_id}"
        pod_spec = self._get_pod_spec(session_id, username, vnc_password)

        try:
            self._core_api.create_namespaced_pod(
                namespace=self._namespace, body=pod_spec
            )
            logger.info(f"Created pod {pod_name} in namespace {self._namespace}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.warning(f"Pod {pod_name} already exists, reusing")
            else:
                raise

        # Wait for pod IP
        pod_ip = self._wait_for_pod_ip(pod_name)
        logger.info(f"Pod {pod_name} started with IP {pod_ip}")

        return ContainerInfo(container_id=pod_name, container_ip=pod_ip, backend="kubernetes")

    def destroy_container(self, container_id: str) -> None:
        """
        Destroy a VNC Pod.

        Args:
            container_id: Pod name
        """
        try:
            self._core_api.delete_namespaced_pod(
                name=container_id,
                namespace=self._namespace,
                grace_period_seconds=10,
            )
            logger.info(f"Pod {container_id} deleted")
        except ApiException as e:
            if e.status == 404:
                pass  # Already deleted
            else:
                logger.error(f"Error deleting pod {container_id}: {e}")

    def is_container_running(self, container_id: str) -> bool:
        """
        Check if a Pod is running.

        Args:
            container_id: Pod name

        Returns:
            True if running, False otherwise
        """
        try:
            pod = self._core_api.read_namespaced_pod(
                name=container_id, namespace=self._namespace
            )
            return pod.status.phase == "Running"
        except ApiException as e:
            if e.status == 404:
                return False
            logger.warning(f"Error checking pod status: {e}")
            return False

    def get_running_count(self) -> int:
        """
        Get count of running VNC Pods.

        Returns:
            Number of running pods
        """
        try:
            pods = self._core_api.list_namespaced_pod(
                namespace=self._namespace,
                label_selector="guac.managed=true",
                field_selector="status.phase=Running",
            )
            return len(pods.items)
        except ApiException as e:
            logger.error(f"Error counting pods: {e}")
            return 0

    def list_managed_containers(self) -> list[dict]:
        """
        List all managed Pods.

        Returns:
            List of pod info dictionaries
        """
        result = []
        try:
            pods = self._core_api.list_namespaced_pod(
                namespace=self._namespace, label_selector="guac.managed=true"
            )
            for pod in pods.items:
                result.append(
                    {
                        "id": pod.metadata.name,
                        "name": pod.metadata.name,
                        "status": pod.status.phase.lower() if pod.status.phase else "unknown",
                        "labels": pod.metadata.labels or {},
                    }
                )
        except ApiException as e:
            logger.error(f"Error listing pods: {e}")
        return result

    def get_containers_memory_gb(self) -> float:
        """
        Get total memory used by VNC Pods in GB.

        Note: This is an estimate based on resource requests/limits.
        For accurate metrics, use metrics-server or Prometheus.

        Returns:
            Memory usage in GB (estimated)
        """
        try:
            pods = self._core_api.list_namespaced_pod(
                namespace=self._namespace,
                label_selector="guac.managed=true",
                field_selector="status.phase=Running",
            )

            total_bytes = 0
            resources = self._k8s_config.get("resources", {})
            limits = resources.get("limits", {})
            requests = resources.get("requests", {})

            # Use limits if available, otherwise requests, otherwise estimate
            memory_str = limits.get("memory") or requests.get("memory") or "1Gi"

            # Parse memory string (e.g., "512Mi", "2Gi")
            memory_bytes = self._parse_memory(memory_str)

            # Multiply by number of running pods
            total_bytes = memory_bytes * len(pods.items)
            return total_bytes / 1024 / 1024 / 1024

        except ApiException as e:
            logger.error(f"Error getting pod memory: {e}")
            return 0.0

    def get_pool_containers(self) -> list[dict]:
        """
        Get list of available pool containers (running, unclaimed).

        Returns:
            List of pool container info dictionaries
        """
        result = []
        try:
            pods = self._core_api.list_namespaced_pod(
                namespace=self._namespace,
                label_selector="guac.managed=true,guac.pool=true",
                field_selector="status.phase=Running",
            )
            for pod in pods.items:
                labels = pod.metadata.labels or {}
                # Only include if not yet claimed (no username label)
                if "guac.username" not in labels:
                    result.append({
                        "id": pod.metadata.name,
                        "session_id": labels.get("guac.session.id", ""),
                        "ip": pod.status.pod_ip,
                    })
        except ApiException as e:
            logger.error(f"Error listing pool pods: {e}")
        return result

    def claim_container(self, pod_name: str, username: str) -> bool:
        """
        Claim a pool container for a specific user by updating its labels.

        Args:
            pod_name: Name of the pod to claim
            username: Username to assign

        Returns:
            True if claimed successfully, False otherwise
        """
        try:
            # Patch the pod labels
            patch_body = {
                "metadata": {
                    "labels": {
                        "guac.pool": "false",
                        "guac.username": username,
                    }
                }
            }
            self._core_api.patch_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
                body=patch_body,
            )
            logger.info(f"Claimed pool pod {pod_name} for user {username}")
            return True
        except ApiException as e:
            logger.error(f"Error claiming pod {pod_name}: {e}")
            return False

    @staticmethod
    def _parse_memory(memory_str: str) -> int:
        """
        Parse Kubernetes memory string to bytes.

        Args:
            memory_str: Memory string (e.g., "512Mi", "2Gi")

        Returns:
            Memory in bytes
        """
        memory_str = str(memory_str).strip()

        units = {
            "Ki": 1024,
            "Mi": 1024**2,
            "Gi": 1024**3,
            "Ti": 1024**4,
            "K": 1000,
            "M": 1000**2,
            "G": 1000**3,
            "T": 1000**4,
        }

        for suffix, multiplier in units.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[: -len(suffix)]) * multiplier)

        # Assume bytes if no unit
        try:
            return int(memory_str)
        except ValueError:
            return 1024**3  # Default to 1Gi
