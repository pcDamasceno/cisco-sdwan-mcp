# Deploying through Styrmin

[Styrmin](https://github.com/opsmill/styrmin) deploys applications from an
**Application Driver** — a versioned spec that says which Helm chart to use, how
to template its values, which workloads make up the application, and what it
exposes. This repository *is* a driver: `driver.styrmin.yml` and `values.j2.yml`
sit at the repository root because Styrmin clones the repo and reads them from
there. Those paths are fixed, not per-driver.

| File | Role |
|---|---|
| [`../driver.styrmin.yml`](../driver.styrmin.yml) | The spec: chart reference, component, service, parameters |
| [`../values.j2.yml`](../values.j2.yml) | Jinja2 template producing the chart's values from the deployment context |
| [`helm/cisco-sdwan-mcp/`](helm/cisco-sdwan-mcp) | The chart the driver deploys |

There is no `actions.py`: the server is stateless, holds no schema, and needs
no migration or seeding step, so the chart alone covers install, upgrade and
uninstall.

---

## Prerequisites

1. **The chart is published.** Merge a change under `deploy/helm/` to `main`, or
   run the `Helm chart` workflow manually. See
   [`helm/README.md`](helm/README.md).
2. **A matching image tag exists.** The application version chosen at deploy
   time becomes the image tag, and `build-push-ghcr` publishes those from
   v-prefixed git tags. Before deploying `0.1.0`:

   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   ```

3. **Both GHCR packages are pullable by the cluster.** `cisco-sdwan-mcp` and
   `charts/cisco-sdwan-mcp` are public today, so nothing is needed here. A GHCR
   package published under a new name starts out private and would need to be
   made public or covered by a pull secret.
4. **The credentials Secret exists in the deployment namespace.** Styrmin
   creates the namespace, so this is a step *after* the deployment is created,
   or handled by ExternalSecrets. See [`helm/README.md`](helm/README.md#the-credentials-secret).

---

## Load the driver

```bash
styrminctl drivers load-version \
  https://github.com/pcDamasceno/cisco-sdwan-mcp.git \
  main
```

Each load creates a new Application Driver Version pinned to the commit at the
branch tip; loading the same commit twice is a no-op. For a private repository,
the Styrmin server needs `STYRMIN_DRIVER_TOKEN` set — the token stays
server-side, so the command itself is unchanged.

## Deploy

```bash
styrminctl deployments create cisco-sdwan-mcp 0.1.0 <environment-id>
```

`sdwan_vmanage_url` is the only parameter with no default, so it must be
supplied. Everything else is optional — the full list, with what each one does,
is in [`../driver.styrmin.yml`](../driver.styrmin.yml).

---

## What the driver exposes

**One component, `server`**, selected by `app.kubernetes.io/name:
cisco-sdwan-mcp`. Stateless, so it declares no backup strategy.

**One service, `cisco-sdwan-mcp`**, http on port 8000, scope `external`.
In-cluster consumers reach it at `cisco-sdwan-mcp:8000`; with
`ingress_enabled` (the default) it is also served on the environment's
generated FQDN. The MCP endpoint is at `/mcp` on both.

**Parameters** for the vManage connection, TLS trust, write protection,
replicas, log level, ingress, and MCP client authentication.

**Per-deployment env vars** for everything else the server reads. The driver
documents the useful ones under `spec.env_vars`, and they surface in the
Styrmin UI; any variable from [`../.env.example`](../.env.example) works, since
they are rendered under `env:` and override the chart's own ConfigMap.

---

## Credentials

Styrmin has no secret-typed parameter — parameter values are stored and land in
the HelmRelease in plain text. So the vManage password never passes through the
driver: `sdwan_credentials_secret` names a Secret in the deployment namespace,
and the chart reads it with `envFrom`. Every key in that Secret becomes an
environment variable, so MCP auth secrets belong there too.

Until the Secret exists the pods sit in `CreateContainerConfigError`. That is
the intended failure mode — the alternative is a server that starts up
half-configured.

---

## Changing the driver

Driver versions are immutable. To publish a change, commit it and load again;
Styrmin creates a new version and existing deployments stay on the one they
pinned until upgraded. Bump `spec.version` when the change is meaningful to
operators — resolution is latest-wins on that field, with load time breaking
ties.

Chart changes need the chart published first, and
`spec.helm.main.version` bumped to match — see
[`helm/README.md`](helm/README.md#releasing-a-chart-change).
