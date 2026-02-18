FROM ghcr.io/openclaw/openclaw:latest

USER root

# Install Python 3 + pip for the Alpaca trading wrapper scripts
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

# Install alpaca-py into a venv accessible by the node user
RUN python3 -m venv /opt/alpaca-venv && \
    /opt/alpaca-venv/bin/pip install --no-cache-dir "alpaca-py>=0.30.0" pytz && \
    chown -R node:node /opt/alpaca-venv

# Make the venv's python the default python
ENV PATH="/opt/alpaca-venv/bin:$PATH"

USER node
