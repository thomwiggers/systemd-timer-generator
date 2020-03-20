"""Generate systemd timer files"""
import sys

import jinja2
import editor


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
#WAkeSystem=false        # Resume the system from suspend to activate (if supported)
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
    template = _get_jinja_environment().from_string(TEMPLATE_TIMER)
    return template.render(
        service_name=service_name,
        script_name=script_name,
    )


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


if __name__ == "__main__":
    main()
