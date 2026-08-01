# Helm chart

`cisco-sdwan-mcp/` is the chart both plain Helm installs and the
[Styrmin driver](../../driver.styrmin.yml) use. It renders a Deployment,
Service, ConfigMap, ServiceAccount and (optionally) an Ingress — the same shape
as the raw manifests in [`../kubernetes/`](../kubernetes), with the settings
lifted into values.

| | |
|---|---|
| Chart | `oci://ghcr.io/pcdamasceno/charts/cisco-sdwan-mcp` |
| Image | `ghcr.io/pcdamasceno/cisco-sdwan-mcp` |
| Published by | [`.github/workflows/publish-chart.yaml`](../../.github/workflows/publish-chart.yaml) |

---

## The credentials Secret

The chart never carries the vManage password in its values. It reads every key
of the Secret named in `sdwan.existingSecret` (default
`cisco-sdwan-mcp-credentials`) as environment variables, so one Secret covers
`SDWAN_PASSWORD` and any MCP auth secrets:

```bash
kubectl -n <namespace> create secret generic cisco-sdwan-mcp-credentials \
  --from-literal=SDWAN_PASSWORD='...' \
  --from-literal=MCP_AUTH_CLIENT_SECRET='...'    # only if you use an OAuth mode
```

Create it before the release. A pod referencing a missing Secret stays in
`CreateContainerConfigError` rather than starting half-configured — the
intended failure mode.

For development only, `sdwan.password` makes the chart render its own Secret
from a values entry. The password then lives in the release's stored values in
plain text.

---

## Standalone install

```bash
helm install sdwan-mcp oci://ghcr.io/pcdamasceno/charts/cisco-sdwan-mcp \
  --version 0.1.0 \
  --namespace sdwan-mcp --create-namespace \
  --set sdwan.vmanageUrl=https://vmanage.example.com:8443 \
  --set sdwan.username=automation-readonly \
  --set image.tag=0.1.0
```

Read [`../README.md`](../README.md) first — the SD-WAN-specific decisions
(dedicated vManage account, write protection, private CAs, reaching a
management-network controller, vManage session limits) apply here unchanged.

`values.yaml` documents every setting. The ones you will usually touch:

| Value | Default | Notes |
|---|---|---|
| `sdwan.vmanageUrl` | — | Required. Include the port when it is not 443. |
| `sdwan.existingSecret` | `cisco-sdwan-mcp-credentials` | Secret carrying `SDWAN_PASSWORD`. |
| `sdwan.enableWrites` | `false` | `true` registers the configuration-changing tools. |
| `caBundle.existingConfigMap` | `""` | Private vManage CA; sets `SDWAN_CA_BUNDLE`. Prefer this over `sdwan.verifySsl: false`. |
| `mcp.auth.mode` | `none` | Never leave this at `none` on a reachable endpoint. |
| `mcp.statelessHttp` | `true` | Required whenever `replicaCount > 1`. |
| `ingress.enabled` | `false` | MCP clients require HTTPS for remote servers — terminate TLS here. |
| `extraEnv` | `[]` | Any variable from `.env.example` that has no dedicated value. |

---

## Releasing a chart change

Chart versions are immutable once published: Styrmin deployments pin
`spec.helm.main.version`, so overwriting one silently changes what they
resolve to. To release a change:

1. Bump `version` in `cisco-sdwan-mcp/Chart.yaml`.
2. Bump `spec.helm.main.version` in [`../../driver.styrmin.yml`](../../driver.styrmin.yml)
   to match — CI fails the two apart.
3. Merge to `main`. The workflow packages and pushes, and skips if the version
   is already in the registry.

The chart version is independent of the application version: a new application
release needs no chart release, because the driver passes the selected version
through as `image.tag`.

Both GHCR packages (`cisco-sdwan-mcp` and `charts/cisco-sdwan-mcp`) are
currently **public**, so no pull secret is needed. A newly created GHCR package
starts out private — if you publish under a different name, check its
visibility before pointing a cluster at it.

---

## The chart / driver contract

Four things the chart must keep providing for the Styrmin driver to work. CI
templates the chart against
[`cisco-sdwan-mcp/ci/styrmin-values.yaml`](cisco-sdwan-mcp/ci/styrmin-values.yaml)
— a copy of what the driver renders — so breaking one of these fails in CI.

1. **`fullnameOverride` is honoured.** The driver sets
   `styrmin-cisco-sdwan-mcp`; without it Helm builds names from the Styrmin
   release name plus the chart name and overruns the 63-character limit.
2. **`app.kubernetes.io/name: cisco-sdwan-mcp` stays on the pods.** It is the
   driver's component `identifier.label` — the selector Styrmin uses to find,
   scale and route to the workload. It comes from the chart name and is
   deliberately independent of `fullnameOverride`.
3. **`service.port` equals the driver's declared service port (8000).**
   Styrmin's service-discovery Service uses the declared port for both `port`
   and `targetPort`.
4. **`command` / `args` tolerate an empty list.** The driver emits both keys
   unconditionally — HelmRelease values are applied as a JSON merge-patch, so an
   omitted key would leave a cleared override in place. The templates consume
   them under `{{- with }}`, where an empty list falls through to the image's
   own entrypoint.
