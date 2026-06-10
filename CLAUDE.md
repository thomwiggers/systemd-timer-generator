# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small CLI tool (`generate-systemd-timer`) that generates a systemd `.timer`/`.service` unit pair from templates, opens them in `$EDITOR`, validates them with `systemd-analyze verify`, and optionally installs them (user or system scope). All logic lives in a single module: `systemd_generator/__init__.py`.

## Commands

Uses `uv` for everything (Python >= 3.8 supported — keep code 3.8-compatible; ruff `target-version = "py38"` enforces some of this).

```sh
uv run pytest -m "not docker"        # fast unit tests
uv run pytest -m docker              # Docker integration tests (needs Docker daemon; builds a systemd image on first run, slow)
uv run pytest tests/test_generator.py::test_name   # single test
uvx ruff check .                     # lint
uvx ruff format .                    # format
uv build                             # build sdist + wheel
```

CI (`.github/workflows/tests.yml`) runs ruff check + format check, pytest on Python 3.8–3.13, and the docker-marked tests in a separate job.

## Releases — never create manually

Releases MUST go through CI (`.github/workflows/main.yml`). Do not run `twine upload`, create GitHub releases by hand, or publish in any other way. The process is:

1. Bump `version` in `pyproject.toml`.
2. Push a tag named `v<version>` — CI verifies the tag matches `uv version --short` exactly, then builds, creates the GitHub release, and publishes to PyPI (trusted publishing).

## Architecture notes

- Unit file content comes from Jinja2 string templates (`TEMPLATE_TIMER`, `TEMPLATE_SERVICE`) embedded in `systemd_generator/__init__.py`. Most directives are intentionally commented out with explanatory comments — the user uncomments what they need in the editor. Comment formatting matters: tests assert that active directive lines are valid systemd syntax.
- Validation flow: after editing, `_validate()` runs `systemd-analyze verify`; on failure the verify output is appended to each unit file as a delimited comment block (`# === systemd-analyze verify ===` … `# === end ... ===`) and the editor reopens. `_strip_verify_comments` removes the block before re-verifying so annotations never accumulate or get fed back to verify.
- Everything interactive degrades gracefully: prompts return defaults when stdin is not a TTY, and validation/install are skipped when `systemd-analyze`/`systemctl` are missing (the tool is developed on macOS but targets Linux).
- `tests/test_generator.py` covers rendering, prompts, install, and `main` with mocks; `tests/test_docker_integration.py` (marked `docker`) runs the real `systemd-analyze verify` inside a Debian container built from `tests/docker/Dockerfile`.
