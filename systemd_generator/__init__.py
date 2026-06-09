"""Generate systemd timer files"""
import os
import subprocess
import sys

import jinja2
import editor


USER_UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
SYSTEM_UNIT_DIR = "/etc/systemd/system"


TEMPLATE_TIMER = """\
[Unit]
Description=Generated timer for {{ service_name }} by {{ script_name }}

[Timer]
#Unit={{ service_name }}.service

# Select one of the following
#OnCalendar=          # daily / weekly / monthly
#OnActiveSec=         # Time after this timer has been loaded
#OnBootSec=           # Time relative to boot
#OnStartupSec=        # Time relative to systemd manager start; relevant for user login
#OnUnitActiveSec=     # Defines it relative to when the to-be-started unit was last activated
#OnUnitInactiveSec=   # Defines it relative to when the to-be-started unit was last deactivated

# Optional settings
#AccuracySec=1m          # Defines the accuracy with which this timer shall elapse
#RandomizedDelaySec=0    # Defines a randomized delay to be added to the start time
#Persistent=false        # Also activate if the timer expired while timer was inactive
                         # Only relevant for OnCalendar

# Probably not necessary
#OnClockChange=false     # Activate this unit whenever the clock jumps
#OnTimezoneChange=false  # Activate whenever the timezone changes
#WakeSystem=false        # Resume the system from suspend to activate (if supported)
#RemainAfterElapse=true  # Keeps the timer in the service manager once elapsed.

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


def _manual_instructions(service_name, target):
    print(
        "\nTo install manually:\n"
        f"  cp {service_name}.service {service_name}.timer {target}/\n"
        f"  systemctl daemon-reload\n"
        f"  systemctl enable --now {service_name}.timer"
    )


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
        if _prompt_yes_no(f"Directory {target} does not exist. Create it?", default=True):
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

    with open(f'{service_name}.service', 'w') as f:
        f.write(_render_service(service_name))
    editor.edit(filename=f'{service_name}.service')
    with open(f'{service_name}.timer', 'w') as f:
        f.write(_render_timer(service_name))
    editor.edit(filename=f'{service_name}.timer')

    if _prompt_yes_no(
        f"\nGenerated {service_name}.service and {service_name}.timer.\n"
        "Install them now?",
        default=False,
    ):
        _install(service_name)


if __name__ == "__main__":
    main()
