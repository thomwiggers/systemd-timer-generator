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
# OnUnitInactiveSec: Defines it relative to when the to-be-started unit was last deactivated
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
