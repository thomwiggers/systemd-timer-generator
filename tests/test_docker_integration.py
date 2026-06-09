"""Integration tests that run the generated units through a real
``systemd-analyze verify`` inside a Docker container.

These are slow (they build an image with systemd on first run) and require a
working Docker daemon, so the whole module is skipped when Docker is
unavailable. Select them explicitly with ``-m docker``.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

import systemd_generator as sg

pytestmark = pytest.mark.docker

IMAGE_TAG = "systemd-timer-generator-test"
DOCKERFILE_DIR = Path(__file__).parent / "docker"


def _docker_available():
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


if not _docker_available():
    pytest.skip("docker is not available", allow_module_level=True)


@pytest.fixture(scope="session")
def systemd_image():
    """Build (and cache) the systemd image once per session."""
    build = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, str(DOCKERFILE_DIR)],
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        pytest.fail(f"docker build failed:\n{build.stdout}\n{build.stderr}")
    return IMAGE_TAG


def _verify_in_docker(image, unit_dir, names):
    """Run ``systemd-analyze verify`` on ``names`` inside the container."""
    args = [f"/units/{name}" for name in names]
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{unit_dir}:/units:ro",
            image,
            "verify",
            *args,
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_generated_units_pass_real_verify(systemd_image, tmp_path):
    """The boilerplate produced by the generator is valid systemd syntax.

    Mirrors the post-edit state: an ``OnCalendar`` is uncommented so the timer
    actually has an elapse setting.
    """
    service = sg._render_service("backup")
    timer = sg._render_timer("backup").replace("#OnCalendar=", "OnCalendar=daily")

    (tmp_path / "backup.service").write_text(service)
    (tmp_path / "backup.timer").write_text(timer)

    rc, output = _verify_in_docker(
        systemd_image, tmp_path, ["backup.service", "backup.timer"]
    )

    assert rc == 0, f"verify rejected generated units:\n{output}"


def test_invalid_unit_fails_real_verify(systemd_image, tmp_path):
    """A broken directive is rejected, confirming verify actually checks."""
    (tmp_path / "backup.service").write_text(
        "[Service]\nType=oneshot\nExecStart=/bin/true\n"
    )
    (tmp_path / "backup.timer").write_text(
        "[Timer]\nOnCalendar=definitely not a calendar\n"
        "[Install]\nWantedBy=timers.target\n"
    )

    rc, output = _verify_in_docker(
        systemd_image, tmp_path, ["backup.service", "backup.timer"]
    )

    assert rc != 0
    assert "calendar" in output.lower()
