# Ubuntu 24.04 Prerequisites

Install the system packages:

```bash
sudo apt-get install -y \
    python3 \
    python3-venv \
    python3-tk \
    ca-certificates \
    ffmpeg \
    xdg-utils
```

Install uv (the Python environment manager):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal or run `source ~/.local/bin/env` so that `uv` is on PATH.

Models and VAD (voice activity detection) weights are downloaded by the application on first use.

---

A full Ubuntu source-install guide with step-by-step instructions will be added in ticket 13.
