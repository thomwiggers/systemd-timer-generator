"""Generate systemd timer files"""

import os
import shutil
import subprocess
import sys

import editor
import jinja2

USER_UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
SYSTEM_UNIT_DIR = "/etc/systemd/system"


TEMPLATE_TIMER = """\
[Unit]
Description=Generated timer for {{ service_name }} by {{ script_name }}

[Timer]
#Unit={{ service_name }}.service

# Select one of the following
# OnCalendar: daily / weekly / monthly
#OnCalendar=
# OnActiveSec: Time after this timer has been loaded
#OnActiveSec=
# OnBootSec: Time relative to boot
#OnBootSec=
# OnStartupSec: Time relative to systemd manager start; relevant for user login
#OnStartupSec=
# OnUnitActiveSec: Defines it relative to when the to-be-started unit was last activated
#OnUnitActiveSec=
# OnUnitInactiveSec: Defines it relative to when the to-be-started unit
# was last deactivated
#OnUnitInactiveSec=

# Optional settings
# AccuracySec: Defines the accuracy with which this timer shall elapse
#AccuracySec=1m
# RandomizedDelaySec: Defines a randomized delay to be added to the start time
#RandomizedDelaySec=0
# Persistent: Also activate if the timer expired while timer was inactive
# Only relevant for OnCalendar
#Persistent=false

# Probably not necessary
# OnClockChange: Activate this unit whenever the clock jumps
#OnClockChange=false
# OnTimezoneChange: Activate whenever the timezone changes
#OnTimezoneChange=false
# WakeSystem: Resume the system from suspend to activate (if supported)
#WakeSystem=false
# RemainAfterElapse: Keeps the timer in the service manager once elapsed.
#RemainAfterElapse=true

[Install]
WantedBy=timers.target

# vim : set ft=systemd.timer :
"""

TEMPLATE_SERVICE = """\
[Unit]
Description=Generated service for {{ service_name }} by {{ script_name }}

[Service]
Type=oneshot
ExecStart=/bin/true

[Install]
WantedBy=multi-user.target

# See https://www.freedesktop.org/software/systemd/man/systemd.service.html#Examples

# vim : set ft=systemd.service :
"""


def _get_jinja_environment():
    env = jinja2.Environment()
    return env


def _render_timer(service_name):
    """Render the systemd.template file"""
    script_name = sys.argv[0]
    template = _get_jinja_environment().from_string(TEMPLATE_TIMER)
    return template.render(
        service_name=service_name,
        script_name=script_name,
    )


def _render_service(service_name):
    """Render the systemd.service file"""
    script_name = sys.argv[0]
    template = _get_jinja_environment().from_string(TEMPLATE_SERVICE)
    return template.render(
        service_name=service_name,
        script_name=script_name,
    )


def _prompt_yes_no(question, default=False):
    """Ask a yes/no question on stdin. Returns the default if non-interactive."""
    if not sys.stdin.isatty():
        return default
    options = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {options} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def _run(cmd):
    """Echo and run a command, returning its exit code."""
    print(f"+ {' '.join(cmd)}")
    return subprocess.call(cmd)


def _has_command(name):
    """Return whether ``name`` is an executable on the PATH."""
    return shutil.which(name) is not None


def _manual_instructions(service_name, target):
    print(
        "\nTo install manually:\n"
        f"  cp {service_name}.service {service_name}.timer {target}/\n"
        f"  systemctl daemon-reload\n"
        f"  systemctl enable --now {service_name}.timer"
    )


VERIFY_COMMENT_BEGIN = "# === systemd-analyze verify ==="
VERIFY_COMMENT_END = "# === end systemd-analyze verify ==="


def _verify(units):
    """Run ``systemd-analyze verify`` capturing its output.

    Returns ``(returncode, output)`` where ``output`` is the combined
    stdout/stderr (systemd-analyze reports problems on stderr).
    """
    cmd = ["systemd-analyze", "verify", *units]
    print(f"+ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode, proc.stdout


def _strip_verify_comments(text):
    """Remove a previously-inserted verify comment block from unit text."""
    out = []
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == VERIFY_COMMENT_BEGIN:
            skipping = True
            continue
        if stripped == VERIFY_COMMENT_END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "".join(out)


def _clear_verify_comments(path):
    """Drop any verify comment block from the unit file at ``path``."""
    with open(path) as f:
        text = f.read()
    with open(path, "w") as f:
        f.write(_strip_verify_comments(text))


def _annotate_with_verify(path, output):
    """Append ``output`` as a verify comment block to the unit at ``path``.

    Any existing block is replaced so the annotations do not accumulate.
    """
    with open(path) as f:
        text = _strip_verify_comments(f.read())
    if text and not text.endswith("\n"):
        text += "\n"
    block_lines = [VERIFY_COMMENT_BEGIN]
    for line in output.splitlines():
        block_lines.append(f"# {line}".rstrip())
    block_lines.append(VERIFY_COMMENT_END)
    with open(path, "w") as f:
        f.write(text + "\n".join(block_lines) + "\n")


def _validate(service_name):
    """Run ``systemd-analyze verify`` on the generated units.

    The combined verify output is echoed and, on failure, appended to each
    unit file as a comment block so the problems are visible when the file is
    reopened in the editor. Returns ``True`` when the units are valid (or when
    ``systemd-analyze`` is unavailable and validation is skipped), ``False``
    when verify reports problems.
    """
    if not _has_command("systemd-analyze"):
        print("systemd-analyze not found; skipping validation.")
        return True
    units = [f"{service_name}.service", f"{service_name}.timer"]
    # Verify the clean files; never feed a previous annotation back in.
    for unit in units:
        _clear_verify_comments(unit)
    returncode, output = _verify(units)
    if output.strip():
        print(output)
    if returncode == 0:
        print("Units passed systemd-analyze verify.")
        return True
    for unit in units:
        _annotate_with_verify(unit, output)
    print(
        "systemd-analyze verify reported problems; "
        "annotated the units (see the comment block).",
        file=sys.stderr,
    )
    return False


def _install(service_name):
    """Offer to copy the units into place, reload systemd and enable the timer."""
    units = [f"{service_name}.service", f"{service_name}.timer"]

    user_scope = _prompt_yes_no(
        "Install as a user unit (instead of system-wide)?", default=True
    )
    if user_scope:
        target = USER_UNIT_DIR
        sudo = []
        systemctl = ["systemctl", "--user"]
    else:
        target = SYSTEM_UNIT_DIR
        sudo = ["sudo"]
        systemctl = ["sudo", "systemctl"]

    if not _prompt_yes_no(f"Copy units into {target} now?", default=True):
        _manual_instructions(service_name, target)
        return

    if not os.path.isdir(target):
        if _prompt_yes_no(
            f"Directory {target} does not exist. Create it?", default=True
        ):
            if _run(sudo + ["mkdir", "-p", target]) != 0:
                print("Failed to create directory; aborting install.", file=sys.stderr)
                return
        else:
            _manual_instructions(service_name, target)
            return

    for unit in units:
        if _run(sudo + ["cp", unit, os.path.join(target, unit)]) != 0:
            print(f"Failed to copy {unit}; aborting install.", file=sys.stderr)
            return

    _run(systemctl + ["daemon-reload"])

    if _prompt_yes_no(f"Enable and start {service_name}.timer now?", default=True):
        _run(systemctl + ["enable", "--now", f"{service_name}.timer"])


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <service name>", file=sys.stderr)
        sys.exit(1)

    service_name = sys.argv[1]

    with open(f"{service_name}.service", "w") as f:
        f.write(_render_service(service_name))
    editor.edit(filename=f"{service_name}.service")
    with open(f"{service_name}.timer", "w") as f:
        f.write(_render_timer(service_name))
    editor.edit(filename=f"{service_name}.timer")

    print(f"\nGenerated {service_name}.service and {service_name}.timer.")

    # Validate; on failure the units are annotated with the problems and the
    # editor is reopened so they can be fixed. Only loop when interactive.
    while not _validate(service_name):
        if not (
            sys.stdin.isatty()
            and _prompt_yes_no(
                "Validation failed. Re-edit the units to fix it?", default=True
            )
        ):
            break
        editor.edit(filename=f"{service_name}.service")
        editor.edit(filename=f"{service_name}.timer")

    if not _has_command("systemctl"):
        print("systemctl not found; skipping install.")
        return

    if _prompt_yes_no("Install them now?", default=False):
        _install(service_name)


if __name__ == "__main__":
    main()
