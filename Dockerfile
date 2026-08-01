# ============================================================
# Stage 1 – Install dependencies
# ============================================================
FROM python:3.13-slim AS builder

WORKDIR /app

# Optional corporate CA certificates.
# Drop any .crt/.pem files into certificates/ and they are added to the trust
# store automatically — no Dockerfile changes needed. The directory may be empty.
COPY certificates/ /tmp/ca-certs/
RUN set -eu; \
    mkdir -p /usr/local/share/ca-certificates; \
    installed=0; \
    for f in /tmp/ca-certs/*.pem /tmp/ca-certs/*.crt; do \
        [ -e "$f" ] || continue; \
        cp "$f" "/usr/local/share/ca-certificates/$(basename "${f%.*}").crt"; \
        installed=1; \
    done; \
    if [ "$installed" -eq 1 ]; then update-ca-certificates; fi; \
    rm -rf /tmp/ca-certs

# Point SSL-aware tooling at the system bundle so builds work behind a
# TLS-intercepting proxy when certificates/ is populated.
#   PIP_CERT           → pip
#   REQUESTS_CA_BUNDLE → requests/urllib3 (used by the hatchling build backend)
#   SSL_CERT_FILE      → OpenSSL-linked clients (httpx, aiohttp, …)
#   CURL_CA_BUNDLE     → curl / libcurl
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Create isolated virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# README.md too: pyproject declares it as the long description, so the build
# backend needs it present to resolve metadata.
COPY pyproject.toml README.md ./
# Minimal cisco_sdwan_mcp/ lets pip resolve PEP 517 project metadata
RUN mkdir -p cisco_sdwan_mcp && pip install --no-cache-dir .

# ============================================================
# Stage 2 – Runtime image
# ============================================================
FROM python:3.13-slim AS runtime

WORKDIR /app

# Carry the trusted CA bundle into the runtime stage so the running
# application can make outbound HTTPS calls through an intercepting proxy.
COPY --from=builder /usr/local/share/ca-certificates/ /usr/local/share/ca-certificates/
RUN update-ca-certificates

# Copy virtual-env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Keep SSL trust working for any outbound HTTPS calls the app makes
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY README.md .
COPY cisco_sdwan_mcp/ ./cisco_sdwan_mcp/

RUN useradd --create-home --shell /bin/bash --uid 10001 appuser \
    && chown -R appuser:appuser /app
# Numeric, not "appuser": with runAsNonRoot the kubelet has to prove the user
# is not root before starting the container, and it cannot resolve a username
# out of the image config. A named USER fails with CreateContainerConfigError.
USER 10001:10001

EXPOSE 8000

# Container-level health check against the unauthenticated /healthz route.
# Kubernetes ignores this (it uses its own probes); docker run / compose use it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0) if os.getenv('MCP_TRANSPORT','http')=='stdio' else urllib.request.urlopen('http://127.0.0.1:'+os.getenv('MCP_PORT','8000')+'/healthz', timeout=4)"

CMD ["python", "-m", "cisco_sdwan_mcp.server"]
