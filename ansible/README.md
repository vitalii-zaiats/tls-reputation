# tls-reputation deployment

Ansible automation for the three deployable components. Each one is
independently deployable; you never have to run the whole thing to ship a
change to one part.

| Component  | Playbook       | Where it runs     | What it is                                       |
|------------|----------------|-------------------|--------------------------------------------------|
| backend    | `backend.yml`  | `tlsrep_backend`  | FastAPI/uvicorn container on 127.0.0.1:8000 + host PostgreSQL 16 |
| frontend   | `frontend.yml` | `tlsrep_frontend` | Vue 3 SPA in an nginx container on 127.0.0.1:8080 |
| proxy      | `proxy.yml`    | `tlsrep_proxy`    | asyncio HTTP CONNECT collector container on exit nodes |

`site.yml` runs all three in dependency order.

Target OS is Ubuntu 24.04 LTS. The playbooks assert this on every run.

**Nothing is built on the servers.** Images are built for `linux/amd64` on your
laptop by the repo's `Makefile`, pushed to GHCR, and pulled from there. Ansible
installs Docker Engine, pulls an image, and runs it. There is no source tree,
no virtualenv, no `uv`, no Node and no `npm` on any target.

---

## Prerequisites

On your laptop (the control machine):

```bash
python3 -m pip install --user ansible-core
ansible-galaxy collection install -r requirements.yml
```

You also need Docker with `buildx` (Docker Desktop, or `docker-ce` +
`docker-buildx-plugin`) to build the images. Nothing beyond an SSH daemon is
required on the targets — the `docker` role installs the rest.

> On an Apple Silicon Mac the default `docker` builder cannot emit
> `linux/amd64`. The Makefile creates a `docker-container` builder
> (`tlsrep-builder`) automatically; you do not have to do anything.

---

## The deploy loop

```bash
# From the repo root, not from ansible/.
make push          # build all three for linux/amd64 and push to ghcr.io
make deploy        # push, then run site.yml with the tag that was just pushed
```

`make deploy` is `make push` followed by

```bash
cd ansible && ansible-playbook site.yml -e tlsrep_image_tag=<VERSION>
```

`VERSION` defaults to the short git SHA, with `-dirty` appended if the tree has
uncommitted changes — so a deployed image is always traceable to a commit, and
an image built from uncommitted code can never be mistaken for one that was.

Per-component equivalents, which are what you will use most of the time:

```bash
make deploy-backend     # push-backend  + ansible-playbook backend.yml
make deploy-frontend    # push-frontend + ansible-playbook frontend.yml
make deploy-proxy       # push-proxy    + ansible-playbook proxy.yml
```

Pass extra Ansible flags through:

```bash
make deploy ANSIBLE_FLAGS="--check --diff --ask-vault-pass"
make deploy-proxy ANSIBLE_FLAGS="--limit exit2.tls-reputation.com"
```

### Deploying a specific tag without rebuilding

Every push publishes two tags: the version (`a1b2c3d`) and `latest`. To deploy
an image that already exists in the registry, skip the Makefile and name the
tag:

```bash
cd ansible
ansible-playbook site.yml -e tlsrep_image_tag=a1b2c3d --ask-vault-pass
```

### Rolling back

A rollback is just a deploy of an older tag. There is no separate mechanism,
and nothing has to be rebuilt.

```bash
# What is on the host right now?
ansible tlsrep_backend -a "docker inspect -f '{{ .Config.Image }}' tlsrep-backend"

# What has been published? (needs gh and read:packages)
gh api /user/packages/container/tls-reputation-backend/versions \
  --jq '.[].metadata.container.tags[]' | head

# Go back.
ansible-playbook backend.yml -e tlsrep_image_tag=<previous-sha> --ask-vault-pass
```

Two things make this reliable: the containers are stateless (all state is in
PostgreSQL), and image tags are immutable once pushed. The one thing a rollback
does *not* undo is a schema change — the backend applies `schema.sql` on
startup, and it is additive (`CREATE TABLE IF NOT EXISTS`), so rolling back the
code leaves the newer schema in place. That is fine for additive changes and is
something to think about before you ship a destructive one.

Rollback is only as far back as the images that still exist on the host or in
the registry. The `docker` role prunes images older than a week
(`tlsrep_docker_prune_until`), but only ones nothing references — anything
still in GHCR can always be re-pulled.

### Pinned tags vs `latest`

`tlsrep_image_tag` defaults to `latest`, which is convenient and wrong for
anything you care about:

|                       | `latest`                                      | pinned SHA (`a1b2c3d`)                         |
|-----------------------|-----------------------------------------------|------------------------------------------------|
| What gets deployed    | Whatever was pushed most recently             | Exactly the commit you named                   |
| Re-running the play   | May silently deploy something new             | Idempotent — same bytes every time             |
| Two hosts, two runs   | Can end up on different images                | Always identical                               |
| Rollback              | You have to know the previous SHA anyway      | Just name it                                   |
| Pull cost             | Registry round-trip on every run              | Only when the image is missing locally         |

The playbooks handle this automatically. `tlsrep_image_pull` (in
`group_vars/all/main.yml`) resolves to `always` when the tag is in
`tlsrep_image_mutable_tags` (`latest`, `main`, `edge`, `nightly`) and `missing`
otherwise. A moving tag *must* be re-resolved from the registry on every run,
or `docker_container` would compare the running container against a stale local
copy and conclude nothing changed.

Use pinned tags for real deploys — which is what `make deploy` does. `latest`
exists so that an ad-hoc `ansible-playbook site.yml` still does something
sensible.

### How a new image actually triggers a restart

`community.docker.docker_container` compares the running container's image ID
against the resolved image ID and recreates the container when they differ
(`image_name_mismatch: recreate`, the default). So:

1. `pull: always` (mutable tag) re-resolves the tag from the registry, or
   `pull: missing` (pinned tag) pulls only if it is not already local.
2. The new image ID differs from the running container's.
3. The container is recreated with the new image.

`recreate: true` is deliberately **not** set — that would tear down and restart
the container on every run whether or not anything changed. A no-op deploy
touches nothing.

---

## Bootstrap

### 1. Inventory

```bash
cp inventory/hosts.example.ini inventory/hosts.ini
$EDITOR inventory/hosts.ini
```

`hosts.ini` is gitignored. The backend and frontend normally point at the same
host — two containers on loopback with one host nginx in front of both — so
list it in both groups. The proxies are separate exit nodes.

### 2. Secrets

Vault files live per group. All are gitignored; only the `.example` templates
are committed.

```bash
cd inventory/group_vars

cp tlsrep_backend/vault.yml.example tlsrep_backend/vault.yml
cp tlsrep_proxy/vault.yml.example   tlsrep_proxy/vault.yml

# Only if you want the GHCR pull token in the vault rather than in
# $GHCR_TOKEN. See "GHCR authentication" below.
cp all/vault.yml.example all/vault.yml
```

Generate the values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # db password
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # ingest key
```

Fill them in, then encrypt:

```bash
ansible-vault encrypt tlsrep_backend/vault.yml tlsrep_proxy/vault.yml
```

**`vault_tlsrep_ingest_key` must be identical in both files** — it is a shared
secret between the collectors and the backend's ingest endpoint. If they drift,
ingest starts returning 401 and the proxies silently stop contributing data.

Editing later (decrypts to your `$EDITOR`, re-encrypts on save):

```bash
ansible-vault edit inventory/group_vars/tlsrep_backend/vault.yml
ansible-vault view inventory/group_vars/tlsrep_proxy/vault.yml
```

Every command that touches secrets needs the vault password. Either pass
`--ask-vault-pass`, or avoid the prompt with a password file:

```bash
echo "my-vault-password" > .vault_pass && chmod 600 .vault_pass
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass    # .vault_pass is gitignored
```

On macOS you can keep it in the keychain instead of on disk:

```bash
security add-generic-password -a "$USER" -s ansible-vault-tlsrep -w
printf '#!/bin/sh\nsecurity find-generic-password -a "$USER" -s ansible-vault-tlsrep -w\n' > .vault_pass
chmod 700 .vault_pass
```

### 3. GHCR authentication

Two different credentials, with deliberately different scopes.

**Your laptop needs push access.** Create a classic PAT at
<https://github.com/settings/tokens> with `write:packages` (which implies
`read:packages`) and store it in your local Docker credential store:

```bash
export GHCR_TOKEN=ghp_xxxxxxxx
echo "$GHCR_TOKEN" | docker login ghcr.io -u vitalii-zaiats --password-stdin
# or: make login
```

That token never leaves your machine and never goes in a vault.

**The servers need pull access.** GHCR publishes every new package as private
regardless of the repository's visibility, so the three `tls-reputation-*`
images are private and an anonymous pull returns `denied`.

Create a **second, read-only** PAT with `read:packages` only — a deploy never
pushes, so the servers must not hold a token that can. Pass it through the
environment:

```bash
export GHCR_TOKEN=ghp_readonly_xxxxxxxx
ansible-playbook site.yml --ask-vault-pass
```

The `docker` role resolves the token in this order:

| Source | Notes |
|---|---|
| `-e tlsrep_ghcr_token=...` | works, but see the warning below |
| `$GHCR_TOKEN` | **preferred** |
| `vault_ghcr_token` | if you would rather keep it in the vault |

> Prefer the environment variable over `-e`. Extra-vars end up in ansible's
> argv, which any local user can read out of `ps` while the play runs, and in
> your shell history afterwards.

To use the vault instead:

```bash
cp inventory/group_vars/all/vault.yml.example inventory/group_vars/all/vault.yml
$EDITOR inventory/group_vars/all/vault.yml     # set vault_ghcr_token
ansible-vault encrypt inventory/group_vars/all/vault.yml
```

**If you would rather not manage a server-side token at all**, make the
packages public: GitHub → your profile → Packages → `tls-reputation-backend` →
Package settings → Change visibility → Public. Repeat for all three. The
`docker` role skips `docker_login` whenever the token resolves to empty, so
nothing else needs changing.

### 4. Deploy SSH keys

Add your public key to `inventory/group_vars/all/main.yml` so the `common` role
can maintain the `deploy` account:

```yaml
tlsrep_deploy_authorized_keys:
  - "ssh-ed25519 AAAAC3Nza... you@laptop"
```

On a brand-new host the `deploy` user does not exist yet, so the very first run
connects as root:

```bash
ansible-playbook site.yml -u root --ask-vault-pass
```

Every run after that uses `deploy` (set in `hosts.ini`).

### 5. DNS before TLS

`tls-reputation.com` and `www.tls-reputation.com` must already resolve to the
app host. Certbot uses the HTTP-01 challenge, so it will fail if DNS is not
live. Test the certificate flow against Let's Encrypt staging first to avoid
burning rate limits:

```bash
ansible-playbook backend.yml -e tlsrep_certbot_staging=true --ask-vault-pass
```

---

## First deploy

```bash
make push                      # from the repo root
cd ansible
ansible-playbook site.yml -e tlsrep_image_tag=$(git rev-parse --short HEAD) --ask-vault-pass
```

Order: base packages and firewall → Docker Engine and GHCR login → PostgreSQL →
backend container → frontend container → nginx and TLS → collector proxies.

Dry run anything first — `--check` is safe throughout:

```bash
ansible-playbook site.yml --check --diff --ask-vault-pass
```

In check mode the tasks that cannot meaningfully be simulated (certbot, the
container tasks when the image is not yet present locally) report as skipped
rather than failing.

---

## Deploying one component

```bash
# Backend only: pull the API image, recreate the container.
ansible-playbook backend.yml -e tlsrep_image_tag=a1b2c3d --ask-vault-pass

# Frontend only: pull the SPA image, recreate the container. No API downtime.
ansible-playbook frontend.yml -e tlsrep_image_tag=a1b2c3d

# All collector proxies.
ansible-playbook proxy.yml -e tlsrep_image_tag=a1b2c3d --ask-vault-pass

# One collector.
ansible-playbook proxy.yml --limit exit2.tls-reputation.com --ask-vault-pass
```

### Tags

```bash
# Pull and re-run containers, skipping all host setup.
ansible-playbook backend.yml --tags deploy --ask-vault-pass

# Skip the slow first-run setup (packages, Docker install, users).
ansible-playbook backend.yml --skip-tags setup --ask-vault-pass

# nginx config only.
ansible-playbook backend.yml --tags config --ask-vault-pass

# Certificates only.
ansible-playbook backend.yml --tags tls --ask-vault-pass
```

Available tags: `setup`, `deploy`, `config`, `tls`, `firewall`, plus per-role
tags (`common`, `docker`, `postgres`, `backend`, `frontend`, `nginx`, `proxy`).

There is no `migrate` tag any more. The backend image applies `schema.sql` from
its FastAPI lifespan hook on startup, so the schema is in place before the
container's healthcheck can pass — and `state: healthy` in the backend role
means a deploy that cannot reach the database fails the play instead of quietly
looking successful.

---

## Rotating the ingest key

The key is shared between the backend and every collector, so **order matters**.
The backend must accept the new key before the proxies start sending it.

```bash
# 1. Set the SAME new value in both vaults.
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
ansible-vault edit inventory/group_vars/tlsrep_backend/vault.yml
ansible-vault edit inventory/group_vars/tlsrep_proxy/vault.yml

# 2. Backend first. The key is container environment, so this recreates the
#    container -- there is no config file to reload in place.
ansible-playbook backend.yml --tags deploy --ask-vault-pass

# 3. Then the collectors.
ansible-playbook proxy.yml --tags deploy --ask-vault-pass

# 4. Confirm ingest is flowing again.
ansible tlsrep_proxy -a "docker ps --filter name=tlsrep-proxy"
ansible tlsrep_proxy -a "docker logs --tail 20 tlsrep-proxy"
```

Note the difference from the file-based setup this replaced: secrets are passed
as container environment, so changing one **recreates the container** rather
than rewriting a file and restarting a unit. `docker_container` notices the env
change on its own — you do not need `--force`, and you do not need a new image
tag. Expect a few seconds of downtime per host at step 2.

Between steps 2 and 3 the collectors are sending the old key and will get 401s.
Keep the gap short. If the backend supports accepting two keys during a
rotation window, deploy both, roll the proxies, then drop the old one.

Rotating the database password is the same shape, but it is used in one place:

```bash
ansible-vault edit inventory/group_vars/tlsrep_backend/vault.yml
ansible-playbook backend.yml --tags setup,deploy --ask-vault-pass
```

The `setup` tag is needed because the PostgreSQL role owns the `ALTER ROLE`.

---

## How code gets to the server

Images, pulled from `ghcr.io`. Nothing else.

```
laptop:  make push  →  docker buildx --platform linux/amd64 --push  →  ghcr.io
server:  ansible    →  docker pull                                  ←  ghcr.io
```

What this buys over the rsync-plus-`uv sync` approach it replaced:

- **The artifact is the same everywhere.** What you tested is the same image
  digest that runs in production, dependencies included. `uv sync` on the
  target could resolve differently than it did locally.
- **Deploys are fast and mostly offline.** Pulling a cached layer set beats
  resolving a dependency tree on a small VPS.
- **Rollback is a tag.** No reverse-rsync, no rebuild.
- **The servers hold no toolchain.** No Python beyond the system one, no Node,
  no compilers, no source. Less to patch and less to exploit.

The cost, honestly: you cannot hotfix by editing a file on the server, and you
cannot deploy uncommitted work without it being marked `-dirty`. That is the
point, but it is a real change in how it feels to work.

Because builds happen on your laptop, that laptop is still the source of truth
for what gets published. Check `git status` before `make push` — the `-dirty`
suffix will tell you afterwards, but by then it is in the registry.

---

## Layout on the target

There is no application directory. Nothing is installed under `/opt`, and
there are no `.env` files under `/etc`.

```
/etc/docker/daemon.json                 log rotation + pinned bridge subnet
/var/lib/docker/                        images and container state
/etc/letsencrypt/live/<domain>/         certificates (host nginx)
/var/www/letsencrypt/                   ACME challenge webroot -- the only
                                        thing the host nginx serves from disk
/etc/postgresql/16/main/                database config (host PostgreSQL)
```

Containers:

| Container        | Published on      | Container port | Notes                     |
|------------------|-------------------|----------------|---------------------------|
| `tlsrep-backend` | `127.0.0.1:8000`  | 8000           | app host                  |
| `tlsrep-frontend`| `127.0.0.1:8080`  | 80             | app host                  |
| `tlsrep-proxy`   | `0.0.0.0:<port>`  | 24761          | exit nodes                |

The backend and frontend are on loopback because the host nginx is the only
public entrypoint on that box. The proxy is the exception: remote clients dial
the collector directly, so it publishes on a routable address.

### The database stays on the host

PostgreSQL is not containerised. It holds the corpus, and durable state should
not share a lifecycle with a stateless image pull.

That has one consequence worth knowing, because it is the least obvious thing
in this repo: inside a container, `127.0.0.1` is the container. So the backend
reaches PostgreSQL across the Docker bridge instead:

- The `docker` role pins the bridge to `172.17.0.0/16` via `bip` in
  `daemon.json`, so the address cannot drift.
- `tlsrep_db_host` is `host.docker.internal`, mapped to the bridge gateway by
  `etc_hosts: {host.docker.internal: host-gateway}` on the container.
- PostgreSQL listens on `127.0.0.1` **and** `172.17.0.1` — not on any routable
  interface.
- `pg_hba.conf` trusts `172.17.0.0/16` for the one role and the one database,
  still `scram-sha-256`. Being on the bridge grants nothing by itself.
- UFW allows the bridge subnet to reach 5432. Traffic from a container to the
  host hits `INPUT`, where the default-deny would otherwise drop it.

Change any one of those five and the backend hangs on connect with nothing
obvious in the logs.

---

## Containers

```bash
docker ps
docker logs -f tlsrep-backend
docker inspect -f '{{ .Config.Image }}' tlsrep-backend    # which tag is live
docker stats --no-stream
```

Every container runs with:

- `restart_policy: unless-stopped` — dockerd is the systemd-managed unit that
  owns container lifecycle, so this is what brings things back after a reboot
  or a crash. `docker.service` is enabled, and `live-restore` keeps containers
  running across a daemon restart.
- `read_only: true` — the root filesystem is immutable. Writable paths are
  explicit `tmpfs` mounts and nothing else: `/tmp` for the Python services,
  plus `/var/cache/nginx` and `/var/run` for the frontend's nginx.
- `cap_drop: [ALL]` — the Python containers need no capabilities at all. The
  frontend adds back exactly four (`NET_BIND_SERVICE`, `SETUID`, `SETGID`,
  `CHOWN`) because nginx binds port 80 in its own namespace and drops its
  workers to an unprivileged user.
- `security_opts: [no-new-privileges:true]` — no setuid escalation.
- `memory` with `memory_swap` set equal to it, so an OOM kills and restarts the
  container rather than degrading the whole host into swap. Plus `pids_limit`
  and, where it matters, `nofile`.
- Capped `json-file` logging (10 MB × 3). The daemon default has no rotation at
  all.

Both application images also run as an unprivileged uid internally
(`useradd --system --uid 10001`), so nothing runs as root in a container.

The backend and frontend images carry a `HEALTHCHECK`, and their roles use
`state: healthy` — the play waits for the container to report healthy and fails
if it does not. The proxy image has no healthcheck (there is nothing to probe
that would not itself open a tunnel), so its role uses `state: started`.

### Debugging a failed container task

The backend and proxy container tasks set `no_log: true`, because their `env`
dicts carry the database password and the ingest key and would otherwise be
printed verbatim in the task result. The cost is that a failure there reports
nothing useful. Go to the host:

```bash
ssh deploy@app1.tls-reputation.com
docker ps -a --filter name=tlsrep-
docker logs --tail 50 tlsrep-backend
docker inspect tlsrep-backend | jq '.[0].State'
```

If you genuinely need the task output, temporarily comment out the `no_log`
line in the role — and remember that a `-vvv` run with it removed will put both
secrets in your terminal scrollback.

---

## Firewall

`common` sets UFW to deny inbound / allow outbound and permits SSH. Roles open
what they need:

- app host: 80 and 443 (nginx role), plus the Docker bridge to 5432 (postgres
  role)
- exit nodes: the configured `tlsrep_proxy_port` only, with 80 and 443
  explicitly denied — these are collectors and must not be reachable as web
  servers

**Know this about Docker and UFW.** Docker publishes ports by DNAT in the
`DOCKER-USER` iptables chain, which is traversed *before* UFW's chains. UFW
rules therefore do not filter traffic to a published container port. In
practice:

- The backend and frontend are unaffected — they publish on `127.0.0.1`, so
  they are not reachable from off-host regardless of firewall rules.
- The collector port on the exit nodes **is** reachable whether or not the UFW
  `allow` rule exists. The rule is kept because it states host policy
  correctly, not because it is doing the work.
- `tlsrep_proxy_allowed_sources` therefore **cannot** be enforced by UFW. The
  proxy role prints a warning if you set it. Enforce source restriction at your
  cloud provider's firewall or security group instead.
- The `deny 80/443` rules on exit nodes still do their job: they govern
  anything listening on the host itself, which is what they were for.

---

## Operational notes

**A no-op deploy changes nothing.** `docker_container` compares the desired
container against the running one — image ID, env, ports, limits — and only
recreates on a real difference. Re-running a play with a pinned tag is a no-op.

**Image changes are what trigger restarts.** See "How a new image actually
triggers a restart" above.

**Certificates renew themselves** via the packaged `certbot.timer`. A deploy
hook reloads the host nginx when a renewal lands. This is unchanged — certbot
and nginx run on the host, not in containers, because certbot needs to write to
the same filesystem nginx reads certificates from.

**Images are pruned weekly.** The `docker` role installs a root cron entry that
runs `docker image prune` for anything unreferenced and older than
`tlsrep_docker_prune_until` (a week by default), so there is always a window of
previous images on disk for an instant rollback. Set
`tlsrep_docker_prune_enabled: false` to turn it off.

**Docker and PostgreSQL are excluded from unattended upgrades.** Both restart
on upgrade. `live-restore` means containers survive a dockerd restart, but an
unattended engine upgrade on a host whose entire workload is containers is not
something to discover after the fact.

**HSTS is set with `preload`.** Once submitted to the preload list, browsers
will refuse plain HTTP for this domain for a long time and removal is slow. Set
`tlsrep_hsts_preload: false` in the nginx role defaults if you are not ready to
commit.

**PostgreSQL runs with `synchronous_commit = off`.** Ingest is append-heavy and
the data is statistical samples, so trading a sub-second window of observations
for much lower fsync pressure is deliberate. Revisit if the database ever holds
something you cannot lose.

**The frontend's API base URL is baked at image build time.** Vite inlines
`VITE_API_BASE` into the bundle, so changing it is a rebuild
(`make push-frontend`), not a re-run of the frontend playbook.
