# Systemd generator for timer units

Generates systemd `.timer` and `.service` units to more easily add cron-like tasks to your system.

After editing the units, the tool can install them for you: copy them into
`/etc/systemd/system` or `$HOME/.config/systemd/user` (creating the directory if
needed), run `systemctl daemon-reload`, and enable and start the timer. The
install step is only offered when `systemctl` is available; otherwise the
generated units are left in the current directory.

After editing, the tool offers to check the units with `systemd-analyze
verify` (when that command is available), so syntax errors are caught before
installation.

## Usage

```sh
generate-systemd-timer unit-name
# Now two editors will pop up to allow you to customize
# Afterwards you'll find unit-name.service and unit-name.timer in the current folder.
# Finally, you'll be asked whether to install, reload and enable the timer.
```
