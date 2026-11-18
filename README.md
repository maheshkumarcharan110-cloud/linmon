# linmon

A small, dependency-light command-line system monitor for Linux. It reports
CPU, RAM, disk, network I/O and uptime, and can run as a live dashboard, log
readings to CSV/JSON, rank top processes, and warn when thresholds are crossed.

## Features

- **Snapshot** — one-time view of CPU, memory, swap, disks, network and uptime.
- **Live dashboard** — refreshing terminal view built with `rich`.
- **Top processes** — busiest processes by CPU and by memory.
- **Logging** — append timestamped readings to CSV or JSON files.
- **Alerts** — CPU/RAM thresholds with optional `notify-send` desktop popups.
- **Scriptable** — `--json` emits a stable, machine-readable snapshot.
- **Resilient** — unreadable sensors, disks and processes are skipped; Ctrl+C
  exits cleanly without a traceback.

## Requirements

- Linux (any modern distribution; tested on Ubuntu 24.04+)
- Python 3.10 or newer
- `psutil` and `rich` (installed automatically)

## Installation

From a checkout, the recommended path is a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install .          # or: pip install -e . for development
.venv/bin/linmon --version
```

For a user-wide install, run `pip install --user .` and make sure
`~/.local/bin` is on your `PATH`. A system-wide install is simply
`sudo pip install .` (a virtual environment or OS package is preferable).

You can also use the Makefile once the virtualenv exists:

```bash
make install
make test
make lint
```

## Usage

```text
usage: linmon [-h] [--live] [--interval SECONDS] [--top N] [--log FILE]
              [--alert-cpu PCT] [--alert-ram PCT] [--json] [--version]
```

### One-time snapshot (default)

```bash
linmon
```

### Live dashboard

Refresh every two seconds by default; change the interval with `--interval`:

```bash
linmon --live
linmon --live --interval 0.5 --top 5
```

Press **Ctrl+C** to quit. The last frame stays on screen.

### Top processes

```bash
linmon --top 10
```

Shows two tables: top 10 by CPU and top 10 by memory (PID, name, usage, RSS).

### Logging

```bash
linmon --log readings.csv
linmon --live --interval 10 --log /var/log/linmon.json
```

CSV files get a header row on first use. JSON files are kept as a valid array
of objects and written atomically, so they can be read while linmon is running.
Parent directories are created automatically. `.csv` and `.json` are the
supported extensions.

### Alerts

```bash
linmon --alert-cpu 90 --alert-ram 85
```

When a threshold is reached (inclusive), linmon prints a warning to stderr and
tries to send a desktop notification through `notify-send` if it is installed.
If your desktop uses D-Bus notifications, install `libnotify-bin`
(`sudo apt install libnotify-bin`). Notifications are not repeated until the
condition clears, which also applies during long-running live sessions.

### JSON output

```bash
linmon --json > snapshot.json
linmon --json | jq '.cpu.percent, .memory.percent'
```

In `--json` mode, log confirmations and alerts are written to stderr so stdout
stays valid JSON. `--json` cannot be combined with `--live`.

### Help and version

```bash
linmon --help
linmon --version
```

## Running as a systemd service

1. Set up an installation and a dedicated user:

   ```bash
   sudo useradd --system --no-create-home --shell /usr/sbin/nologin linmon
   sudo mkdir -p /opt/linmon /var/log/linmon
   sudo python3 -m venv /opt/linmon/.venv
   sudo /opt/linmon/.venv/bin/pip install /path/to/linmon
   sudo cp -r /path/to/linmon/. /opt/linmon/src 2>/dev/null || true
   sudo chown -R linmon:linmon /opt/linmon /var/log/linmon
   ```

2. Copy the example unit and adjust paths if needed:

   ```bash
   sudo cp linmon.service /etc/systemd/system/linmon.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now linmon.service
   sudo journalctl -u linmon.service -f
   ```

The unit runs `linmon --live --interval 5 --log /var/log/linmon/linmon.csv`
with hardened settings. A live dashboard mainly makes sense when attached to a
real terminal; for unattended collection prefer the cron recipe below.

## Running from cron

Cron has no terminal or D-Bus session, so use snapshots and logging (not
`--live`, and do not rely on desktop notifications):

```cron
# Every five minutes, append a CSV reading
*/5 * * * * /opt/linmon/.venv/bin/linmon --log /var/log/linmon/linmon.csv

# Every minute, append a reading only when CPU or RAM is high
* * * * * /opt/linmon/.venv/bin/linmon --alert-cpu 90 --alert-ram 85 --log /var/log/linmon/linmon.csv
```

Alerts go to stderr; cron will email the output if `MAILTO` is configured. To
send email explicitly, pipe stderr through `mail`:

```cron
*/5 * * * * /opt/linmon/.venv/bin/linmon --alert-cpu 90 2>&1 | mail -s "linmon alert" you@example.com
```

## Building a .deb package

The included script vendors linmon and its Python dependencies into a
Debian package (requires `dpkg-dev` and network access for `pip`):

```bash
sudo apt install dpkg-dev
./scripts/build_deb.sh
sudo apt install ./dist/linmon_1.0.0_amd64.deb
linmon --version
```

Override the output directory with `OUTPUT_DIR=/tmp ./scripts/build_deb.sh`.
The package installs `/usr/bin/linmon` and depends only on `python3 (>= 3.10)`.

## Screenshots

This repository is text-only; no binary screenshots are committed. To capture
your own, run the live dashboard and take a terminal screenshot:

```bash
linmon --live --interval 1 --top 5
```

Example snapshot output:

```text
╭────────────── linmon snapshot - 2026-01-01T00:00:00+00:00 ──────────────╮
│ Host      workstation  Linux 6.8.0                                     │
│ Uptime    4d 05h 01m                                                   │
│ CPU       ━━━━━━━╸       33.3%  4 cores  load 2.55/2.60/2.65            │
│ Memory    ━━━━━━━━━━━━━━━ 71.3%  5.1 GiB/7.1 GiB                        │
│ Disk      ━━━━━            22.2%  45.5 GiB/216.1 GiB  / (ext4)         │
│ Network                   down 2.6 GiB  up 1.3 GiB  (cumulative)       │
╰─────────────────────────────────────────────────────────────────────────╯
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
make test        # pytest
make lint        # ruff check
make format      # ruff format
python -m linmon --help   # run from the source tree
```

Tests use `pytest` with mocked psutil data, so they never depend on the state
of the machine they run on.

## License

MIT — see [LICENSE](LICENSE).
