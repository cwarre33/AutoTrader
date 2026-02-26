FROM ghcr.io/openclaw/openclaw:latest

USER root

# Install Python 3 + pip for the Alpaca trading wrapper scripts
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

# Install alpaca-py into a venv accessible by the node user
RUN python3 -m venv /opt/alpaca-venv && \
    /opt/alpaca-venv/bin/pip install --no-cache-dir "alpaca-py>=0.30.0" pytz matplotlib && \
    chown -R node:node /opt/alpaca-venv

# Make the venv's python the default python
ENV PATH="/opt/alpaca-venv/bin:$PATH"

# Default cron: scan every minute (seeded when openclaw-config/cron/jobs.json is missing)
COPY config/cron-jobs-default.json /home/node/cron-jobs-default.json
COPY entrypoint.sh /home/node/entrypoint.sh
# Normalize line endings (CRLF -> LF) so shebang works when built on Windows
RUN sed -i 's/\r$//' /home/node/entrypoint.sh && \
    chown node:node /home/node/cron-jobs-default.json /home/node/entrypoint.sh && \
    chmod +x /home/node/entrypoint.sh

USER node

# Run entrypoint via sh so we don't rely on script shebang (avoids CRLF/shebang issues on Windows)
ENTRYPOINT ["/bin/sh", "/home/node/entrypoint.sh"]
