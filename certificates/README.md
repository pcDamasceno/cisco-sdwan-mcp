# Optional corporate CA certificates

Drop `.crt` or `.pem` files in this directory and the Docker build adds them to
the container trust store automatically (see the `COPY certificates/` step in
the `Dockerfile`). No Dockerfile edits are required.

Leave the directory empty if you do not sit behind a TLS-intercepting proxy —
the build skips the trust-store step when no certificates are present.

Do not commit private keys here. Only public root CA certificates belong in
this directory.
