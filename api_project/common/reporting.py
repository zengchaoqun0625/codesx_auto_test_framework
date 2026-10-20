"""Small, side-effect-free helpers for test reporting."""
import os
from collections.abc import Sequence

from api_project.common.settings import get_bool_env


WORKER_RESULTS_KEY = "api_test_results"


def is_report_upload_enabled(environ=None) -> bool:
    """Return whether uploading reports to an external service is explicitly enabled."""
    return get_bool_env("UPLOAD_TEST_REPORT", default=False, environ=environ)


def is_xdist_worker(config) -> bool:
    """pytest-xdist exposes ``workerinput`` only in worker processes."""
    return hasattr(config, "workerinput")


def publish_worker_results(config, results) -> None:
    """Send a worker's serializable results back to the xdist controller."""
    config.workeroutput[WORKER_RESULTS_KEY] = list(results)


def collect_worker_results(node) -> list:
    """Read a worker payload defensively; malformed payloads are ignored."""
    payload = getattr(node, "workeroutput", {}).get(WORKER_RESULTS_KEY, [])
    return list(payload) if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)) else []
