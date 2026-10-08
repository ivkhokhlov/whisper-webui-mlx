# Private NVIDIA NeMo image cache

This is a Docker Distribution pull-through cache for the public NVIDIA NGC
registry. It keeps the original manifests and layers; it does not rename or
flatten an application image into a base image. Basic authentication is required
for all registry requests. Traefik terminates HTTPS, and port 5000 is only
available on the existing `coolify` Docker network.

The deployed service lives at `/data/mlx-ui-images` on vps-nl and uses
`registry.m10a.space`. This DNS name follows the existing m10a.space ingress
on vps-ru, which forwards HTTP and TLS to vps-nl. No ingress/firewall changes
are required. A hostname pointing directly at vps-nl will not work with the
current external network access rules.

## Installation

Copy `compose.yaml` and `config.yaml` to the service directory. Create a private
`auth` directory and a bcrypt htpasswd entry (the `htpasswd` utility is provided
by `apache2-utils`):

```bash
install -d -m 700 /data/mlx-ui-images/auth
cd /data/mlx-ui-images
htpasswd -Bc auth/htpasswd mlx-ui-builder
chmod 600 auth/htpasswd
printf '%s\n' 'REGISTRY_HOST=registry.m10a.space' > .env
chmod 600 .env
docker compose -p mlx-ui-images up -d
```

Keep passwords in the operator's credential store, never in the repository.
The current deployment keeps its client credential in the root-only
`/data/mlx-ui-images/credentials/client.json`, outside container mounts.

On the build host, run `docker login registry.m10a.space` as the user Coolify
uses to connect to that host (`neo` on home-spark). Coolify mounts that user's
Docker credential file into its build helper. Authentication is shared with
Docker's normal client; no custom download scripts are involved.

## Application build

The canonical default in `Dockerfile.spark` is the official NGC image pinned
to the NVIDIA manifest digest. For this deployment, set the build-time Coolify
variable `NEMO_BASE_IMAGE` to:

```text
registry.m10a.space/nvidia/nemo:26.02.01@sha256:5852a213751955315a5dd54ce50eff69ac87d474f33968135fc88f1cdbb1dd06
```

This variable must be available during builds; a runtime-only variable does
not select the Docker base image. The local launcher accepts the same variable.

## Operations

- Start/update: `docker compose -p mlx-ui-images up -d` from the service directory.
- Inspect: `docker compose -p mlx-ui-images ps` and `logs --tail 100`.
- Back up `compose.yaml`, `config.yaml`, `.env`, and authentication separately
  from the disposable `storage` cache. Keep credential backups private.
- Rotate the htpasswd entry and client credential together, restart the registry,
  and repeat `docker login` on build hosts.
- Distribution's normal proxy cache expiry is seven days. Missing layers are
  fetched again from NGC, so available disk space and upstream access are needed.
  Do not manually delete files in an active cache; use Distribution maintenance
  procedures for a deliberate cache reset.
- To update NeMo, obtain its digest from NVIDIA, update both repository defaults
  and the Coolify build variable, then rebuild and test GPU transcription before
  deploying. Never retag an application image as `nvcr.io/nvidia/nemo`.

Acceptance requires unauthenticated `/v2/` to return 401 over trusted TLS,
authenticated manifest/config digests to match NGC, a normal Docker pull on
home-spark, and real application inference on its GPU.
