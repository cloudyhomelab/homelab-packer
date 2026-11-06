# fapolicyd

dpkg's file lists cover only package files, so these are allowed by location instead of trust:

- scripts under `/var/lib/dpkg/`: maintainer scripts
- shell scripts under `/etc/`: config files, such as cron jobs and grub and initramfs hooks
- Python bytecode under `/usr/lib/python3*`: compiled by maintainer scripts

cloud-init `runcmd` is allowed; `bootcmd` runs from a temporary file and is denied.

The apt hook (`/etc/apt/apt.conf.d/80fapolicyd`) stops a running daemon around each dpkg run; the
restart reloads the trust database. After `dpkg -i` without apt, run `fapolicyd-cli --update`.
