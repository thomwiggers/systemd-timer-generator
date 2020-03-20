# Systemd generator for timer units

Generates systemd `.timer` and `.service` units to more easily add cron-like tasks to your system.

You'll still have to copy them into the right place (either `/etc/systemd/system`
or `$HOME/.config/systemd/user`) and reload systemd using `systemctl daemon-reload`.

## Usage

```sh
generate-systemd-timer unit-name
# Now two editors will pop up to allow you to customize
# Afterwards you'll find unit-name.service and unit-name.timer in the current folder.
```
