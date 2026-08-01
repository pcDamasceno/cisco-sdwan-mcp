# Deployment

The container is a plain HTTP server on port 8000 with an unauthenticated
`/healthz` probe endpoint, so it runs on any container platform. This
directory ships four ready-to-use targets:

| Target | Files | Use it when |
|---|---|---|
| Kubernetes (kustomize) | [`kubernetes/`](kubernetes) (Deployment, Service, Ingress, ConfigMap, Secret example, kustomization) | You want to read and edit the manifests directly |
| Kubernetes (Helm) | [`helm/`](helm) | You deploy several instances, or drive it from a GitOps tool |
| Styrmin | [`styrmin.md`](styrmin.md), plus `driver.styrmin.yml` and `values.j2.yml` at the repository root | Styrmin manages the cluster's applications |
| Google Cloud Run | [`cloud-run-service.yaml`](cloud-run-service.yaml) | Serverless, no cluster |

All of them consume the image published by the `build-push-ghcr` workflow; the
Helm and Styrmin paths also need the chart published by the `publish-chart`
workflow.

---

## Before you deploy anywhere

This server holds credentials to your SD-WAN controller, which makes the
deployment decisions different from a generic MCP server:

1. **Use a dedicated vManage account.** Create one for this server rather than
   reusing an operator's. Give it a read-only role unless you are deliberately
   enabling writes — the vManage account is the real security boundary, not
   `SDWAN_ENABLE_WRITES`.
2. **Keep `SDWAN_ENABLE_WRITES=false`** unless the deployment exists to change
   configuration. With it off, the configuration tools are never registered, so
   no client can call them.
3. **Never expose the server publicly with `MCP_AUTH=none`.** Anyone who
   reaches the endpoint inherits the server's view of your WAN. Either restrict
   at the platform layer (Cloud Run ingress/IAM, Kubernetes NetworkPolicy, VPN)
   or enable `MCP_AUTH` — ideally both.
4. **Put `SDWAN_PASSWORD` in a secret store**, never in a ConfigMap, image
   layer or `cloud-run-service.yaml` literal.
5. **Keep TLS verification on.** If the controller uses a private CA, mount
   the CA and set `SDWAN_CA_BUNDLE` rather than setting
   `SDWAN_VERIFY_SSL=false`.

Reachability matters too: the server must be able to reach vManage's HTTPS
port (commonly 8443) from wherever it runs. Controllers are usually on a
management network, so a cloud deployment typically needs a VPN, VPC
connector or peering — check this before debugging auth errors.

---

## Kubernetes

### Deploy

```bash
# 1. Create the Secret holding the vManage password
kubectl create secret generic mcp-server-secrets \
  --from-literal=SDWAN_PASSWORD='...'

# 2. Set SDWAN_VMANAGE_URL and SDWAN_USERNAME in kubernetes/configmap.yaml,
#    and point kustomization.yaml at your image (images: newName/newTag), then:
kubectl apply -k deploy/kubernetes

# Check it
kubectl get pods -l app.kubernetes.io/name=mcp-server
kubectl logs -l app.kubernetes.io/name=mcp-server | head   # confirms the controller and mode
kubectl port-forward svc/mcp-server 8000:80   # → http://localhost:8000/mcp
```

The startup log line reports which controller and which mode the server came
up in, e.g. `vManage controller: vmanage.example.com:8443 (user
automation-readonly, TLS verify: True)` followed by `Write tools: disabled
(read-only)`. Check it after every deploy.

### What the manifests give you

- **Deployment** — 2 replicas, non-root, read-only root filesystem, all
  capabilities dropped, resource requests/limits, and startup/readiness/liveness
  probes against `/healthz` (served outside MCP auth, so probes keep working
  when `MCP_AUTH` is enabled).
- **ConfigMap** — non-sensitive `MCP_*` and `SDWAN_*` settings.
- **Secret** — `SDWAN_PASSWORD`; see `secret.example.yaml`.
- **Service** — ClusterIP on port 80 → container port 8000.
- **Ingress** — example host with the ingress-nginx annotations that
  streamable HTTP needs (buffering off, long read timeout). Configure TLS:
  MCP clients require HTTPS for remote servers and OAuth will not work
  without it.

`/healthz` deliberately does **not** check vManage. A brief controller outage
should not restart pods or fail readiness — tools report the problem per call
instead, and the server recovers on its own when vManage returns.

### A controller with a private CA

```bash
kubectl create configmap sdwan-ca --from-file=vmanage-ca.pem=/path/to/ca.pem
```

Then uncomment the `volumes`/`volumeMounts` blocks in `deployment.yaml` and set
`SDWAN_CA_BUNDLE: /etc/sdwan-ca/vmanage-ca.pem` in the ConfigMap.

### Scaling notes

The default streamable-HTTP setup is stateless-friendly, but MCP sessions are
held in the pod that created them. With more than one replica, enable session
affinity (sticky sessions) on your ingress controller, or scale to one replica
while evaluating.

Each pod keeps its own authenticated vManage session. vManage limits
concurrent sessions per account, so keep an eye on replica count on a large
deployment rather than scaling out freely.

---

## Helm

Same shape as the manifests above, with the settings lifted into values and the
vManage password read from a Secret you create out-of-band:

```bash
kubectl -n sdwan-mcp create secret generic cisco-sdwan-mcp-credentials \
  --from-literal=SDWAN_PASSWORD='...'

helm install sdwan-mcp oci://ghcr.io/pcdamasceno/charts/cisco-sdwan-mcp \
  --version 0.1.0 \
  --namespace sdwan-mcp --create-namespace \
  --set sdwan.vmanageUrl=https://vmanage.example.com:8443 \
  --set image.tag=0.1.0
```

Chart source, every value, and the release process are in
[`helm/README.md`](helm/README.md).

---

## Styrmin

This repository doubles as a Styrmin Application Driver: `driver.styrmin.yml`
and `values.j2.yml` at the repository root describe how Styrmin should deploy
the Helm chart above, which workloads make up the application, and what it
exposes.

```bash
styrminctl drivers load-version \
  https://github.com/pcDamasceno/cisco-sdwan-mcp.git main

styrminctl deployments create cisco-sdwan-mcp 0.1.0 <environment-id>
```

See [`styrmin.md`](styrmin.md) for the prerequisites — published chart, matching
image tag, credentials Secret — and for how the driver handles credentials.

---

## Google Cloud Run

### Prerequisites

- A Google Cloud project with the Cloud Run API enabled
- `gcloud` authenticated: `gcloud auth login && gcloud config set project PROJECT_ID`
- An image published by the `build-push-ghcr` workflow (or built locally)
- Network reachability from Cloud Run to vManage — usually a Serverless VPC
  connector plus a VPN or interconnect to the management network

### Image source

Cloud Run pulls **public** `ghcr.io` images directly — no Artifact Registry
needed. Make the GitHub package public once, under
**Repository → Packages → Package settings → Change visibility**.

Public images from ghcr.io are cached by Cloud Run for up to one hour, so a
freshly pushed `:latest` may not deploy immediately. Deploy by immutable tag or
digest to avoid this:

```bash
ghcr.io/OWNER/REPO:sha-1a2b3c4
```

For a **private** package, Cloud Run cannot pull it directly. Create an
Artifact Registry remote repository that proxies `ghcr.io` and deploy from
there instead:

```bash
gcloud artifacts repositories create ghcr-proxy \
  --repository-format=docker \
  --mode=remote-repository \
  --remote-docker-repo=https://ghcr.io \
  --location=REGION
# then use: REGION-docker.pkg.dev/PROJECT/ghcr-proxy/OWNER/REPO:TAG
```

### Deploy

Store the vManage password in Secret Manager first:

```bash
echo -n 'the-password' | gcloud secrets create sdwan-password --data-file=-
```

Imperative:

```bash
gcloud run deploy cisco-sdwan-mcp \
  --image ghcr.io/OWNER/REPO:latest \
  --region europe-west3 \
  --port 8000 \
  --cpu 1 --memory 512Mi \
  --min-instances 0 --max-instances 10 --concurrency 80 \
  --ingress internal \
  --set-env-vars SDWAN_VMANAGE_URL=https://vmanage.example.com:8443,SDWAN_USERNAME=automation-readonly,SDWAN_ENABLE_WRITES=false \
  --set-secrets SDWAN_PASSWORD=sdwan-password:latest \
  --vpc-connector CONNECTOR_NAME --vpc-egress private-ranges-only
```

Declarative (keeps settings in version control — preferred):

```bash
# edit deploy/cloud-run-service.yaml, replacing SERVICE_NAME and IMAGE
gcloud run services replace deploy/cloud-run-service.yaml --region europe-west3
```

### Access control

`gcloud run deploy` prompts about unauthenticated access. Cloud Run is private
by default; the service only becomes publicly reachable if you grant it:

```bash
gcloud run services add-iam-policy-binding cisco-sdwan-mcp \
  --region europe-west3 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

> **Do not do this without application auth.** `allUsers` makes the MCP server
> callable by anyone on the internet, and with `MCP_AUTH=none` that means
> anyone can enumerate your WAN — every device, site, address and alarm the
> server can see. Keep IAM restricted to specific principals, or grant
> `allUsers` **and** enable `MCP_AUTH` (`jwt`, `oauth-proxy`, `github`, …).
> The shipped `cloud-run-service.yaml` sets `ingress: internal` for this
> reason; relax it deliberately, not by default.

### Custom domain

Cloud Run assigns a `*.run.app` URL. To use your own hostname, map it with
`gcloud beta run domain-mappings create`, or front the service with an external
HTTPS load balancer and point a DNS record at it.

---

## Verifying a deployment

```bash
curl -s https://<your-host>/healthz
# {"status":"ok","server":"cisco-sdwan-mcp"}
```

`/healthz` answering only proves the process is up. To confirm the vManage
side, call a cheap tool through an MCP client — `get_fabric_summary` is one
round trip and exercises authentication, TLS and reachability at once. A
configuration or credential problem comes back as a readable
`ConfigurationError` / `AuthenticationError` message rather than a stack trace.
