"""Read-only checks shared by setup and removal before any privileged action."""
import os
from pathlib import Path
import stat
import sys


def verify_install_destination(destination, directory=False, private_config=False):
    destination = Path(destination)
    if not destination.is_absolute():
        raise RuntimeError('Install destinations must be absolute')
    # Detect loops before following targets while allowing missing future dirs.
    base = destination if directory else destination.parent
    resolved = base.resolve(strict=False)
    pending = [destination if directory else destination.parent,
               resolved]
    seen = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        if len(seen) > 256:
            raise RuntimeError('Too many directory/symlink components: ' + str(destination))
        pending.extend(path.parents)
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue  # Elevated install/systemd creates these under secure dirs.
        if info.st_uid != 0:
            raise RuntimeError('Install directory is not root-owned: ' + str(path))
        if stat.S_ISLNK(info.st_mode):
            target = Path(os.readlink(path))
            if not target.is_absolute():
                target = path.parent / target
            # Checking only the fully resolved path misses a symlink detour
            # through a writable directory which then links back into /usr.
            pending.append(target)
            if not stat.S_ISDIR(path.stat().st_mode):
                raise RuntimeError('Install directory symlink is not a directory: ' + str(path))
        elif not stat.S_ISDIR(info.st_mode):
            raise RuntimeError('Install parent is not a directory: ' + str(path))
        elif info.st_mode & 0o022:
            raise RuntimeError('Install directory is group/world-writable: ' + str(path))
    if not directory:
        try:
            info = destination.lstat()
        except FileNotFoundError:
            return
        except PermissionError:
            if private_config:
                # /etc/sudoers.d is commonly 0700. All ancestors have already
                # been verified; GNU install replaces the final filename rather
                # than following its symlink, so no untrusted executable is run.
                return
            raise
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Existing install destination is not a secure root-owned file: ' + str(destination))


def verify_install_destinations():
    for path in (
        '/usr/local/libexec/apple-silicon-fan-control',
        '/etc/systemd/system/apple-silicon-fan-watchdog.service',
        '/etc/systemd/system/apple-silicon-fan-sleep.service',
        '/usr/lib/systemd/system-sleep/apple-silicon-fan-control',
        '/var/lib/apple-silicon-fan-control/preference.json',
    ):
        verify_install_destination(path)
    verify_install_destination('/etc/sudoers.d/apple-silicon-fan-control', private_config=True)
    for path in (
        '/var/lib/apple-silicon-fan-control/backups',
        '/run/apple-silicon-fan-control',
        '/etc/systemd/system/multi-user.target.wants',
        '/etc/systemd/system/sleep.target.wants',
        '/etc/tmpfiles.d',
    ):
        verify_install_destination(path, directory=True)


if __name__ == '__main__':
    try:
        verify_install_destinations()
    except (OSError, RuntimeError) as error:
        print('Privileged path safety check failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
