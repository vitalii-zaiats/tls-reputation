# tls-reputation deployment

Ansible automation for the three deployable components. Each one is
independently deployable; you never have to run the whole thing to ship a
change to one part.

| Component  | Playbook       | Where it runs            | What it is                                  |
|------------|----------------|--------------------------|---------------------------------------------|
| backend    | `backend.yml`  | `tlsrep_backend`         | FastAPI/uvicorn on 127.0.0.1:8000 + PostgreSQL 16 |
| frontend   | `frontend.yml` | `tlsrep_frontend`        | Vue 3 SPA, built locally, served by nginx    |
| proxy      | `proxy.yml`    | `tlsrep_proxy`           | asyncio HTTP CONNECT collector on exit nodes |

`site.yml` runs all three in dependency order.

Target OS is Ubuntu 24.04 LTS. The playbooks assert this on every run.

---

## Prerequisites

On your laptop (the control machine):

```bash
python3 -m pip install --user ansible-core
ansible-galaxy collection install -r requirements.yml
```

You also need `rsync` and, for the frontend, Node 20+ with `npm`. Nothing
beyond an SSH daemon is required on the targets.

---

## Bootstrap

### 1. Inventory

```bash
cp inventory/hosts.example.ini inventory/hosts.ini
$EDITOR inventory/hosts.ini
```

`hosts.ini` is gitignored. The backend and frontend normally point at the same
host; the proxies are separate exit nodes.

### 2. Secrets

Two vault files, one per group. Both are gitignored; only the `.example`
templates are committed.

```bash
cd inventory/group_vars

cp tlsrep_backend/vault.yml.example tlsrep_backend/vault.yml
cp tlsrep_proxy/vault.yml.example   tlsrep_proxy/vault.yml
```

Generate the values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # db password
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # ingest key
```

Fill them in, then encrypt both files:

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

Every command below that touches secrets needs the vault password. Either pass
`--ask-vault-pass`, or avoid the prompt by pointing at a password file:

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

### 3. Deploy SSH keys

Add your public key to `inventory/group_vars/all.yml` so the `common` role can
maintain the `deploy` account:

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

### 4. DNS before TLS

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
ansible-playbook site.yml --ask-vault-pass
```

Order: base packages and firewall → PostgreSQL → backend (code, schema, service)
→ frontend (local build, ship `dist/`) → nginx and TLS → collector proxies.

Dry run anything first — `--check` is safe throughout:

```bash
ansible-playbook site.yml --check --diff --ask-vault-pass
```

In check mode the tasks that cannot meaningfully be simulated (`uv sync`, the
schema migration, certbot) report as skipped rather than failing.

---

## Deploying one component

```bash
# Backend only: sync code, uv sync, apply schema.sql, restart the API.
ansible-playbook backend.yml --ask-vault-pass

# Frontend only: npm build locally, rsync dist/, reload nginx. No API downtime.
ansible-playbook frontend.yml

# All collector proxies.
ansible-playbook proxy.yml --ask-vault-pass

# One collector.
ansible-playbook proxy.yml --limit exit2.tls-reputation.com --ask-vault-pass
```

### Tags

```bash
# Config files only, no code sync.
ansible-playbook backend.yml --tags config --ask-vault-pass

# Skip the slow first-run setup (packages, users, uv).
ansible-playbook backend.yml --skip-tags setup --ask-vault-pass

# Re-apply the schema without touching anything else.
ansible-playbook backend.yml --tags migrate --ask-vault-pass

# Certificates only.
ansible-playbook backend.yml --tags tls --ask-vault-pass
```

Available tags: `setup`, `deploy`, `config`, `migrate`, `tls`, `firewall`, plus
per-role tags (`common`, `postgres`, `backend`, `frontend`, `nginx`, `proxy`).

---

## Rotating the ingest key

The key is shared between the backend and every collector, so **order matters**.
The backend must accept the new key before the proxies start sending it.

```bash
# 1. Set the SAME new value in both vaults.
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
ansible-vault edit inventory/group_vars/tlsrep_backend/vault.yml
ansible-vault edit inventory/group_vars/tlsrep_proxy/vault.yml

# 2. Backend first.
ansible-playbook backend.yml --tags config --ask-vault-pass

# 3. Then the collectors.
ansible-playbook proxy.yml --tags config --ask-vault-pass

# 4. Confirm ingest is flowing again.
ansible tlsrep_proxy -a "systemctl is-active tlsrep-proxy"
ansible tlsrep_proxy -a "journalctl -u tlsrep-proxy -n 20 --no-pager"
```

Between steps 2 and 3 the collectors are sending the old key and will get 401s.
Keep the gap short. If the backend supports accepting two keys during a
rotation window, deploy both, roll the proxies, then drop the old one.

Rotating the database password is the same shape, but it is only used in one
place:

```bash
ansible-vault edit inventory/group_vars/tlsrep_backend/vault.yml
ansible-playbook backend.yml --tags config,setup --ask-vault-pass
```

The `setup` tag is needed because the PostgreSQL role owns the `ALTER ROLE`.

---

## How code is shipped

Default is **rsync from your local checkout** (`ansible.posix.synchronize`),
not `git pull` on the server.

For a personal project deployed from one laptop, this is the better trade:
what you tested locally is byte-for-byte what lands on the server, there are no
deploy keys or repo credentials on the hosts, and it works with uncommitted
changes when you need to ship a hotfix. The cost is that the deploying machine
is the source of truth — so whatever you rsync is what runs, committed or not.
Check `git status` before deploying.

The frontend follows the same principle one step further: `npm ci && npm run
build` runs on your laptop and only the built `dist/` is shipped. No Node
toolchain is ever installed on the server.

Excludes (`.venv/`, `__pycache__/`, `tests/`, `.env`, caches) are in each role's
`defaults/main.yml`. `--delete` is on, so files removed locally are removed on
the server.

If you would rather pull from git, replace the `Synchronise the ... source`
task in `roles/backend/tasks/main.yml` (or `roles/proxy/`) with
`ansible.builtin.git` pointing at the repo and a deploy key, and keep the rest
of the role as-is.

---

## Layout on the target

```
/opt/tls-reputation/backend/       backend code + .venv     (deploy:tlsrep 0750)
/opt/tls-reputation/proxy/         proxy code + .venv       (deploy:tlsrep-proxy 0750)
/etc/tls-reputation/backend.env    API secrets              (tlsrep:tlsrep 0640)
/etc/tls-reputation/proxy.env      collector secrets        (tlsrep-proxy 0640)
/var/www/tls-reputation/           built SPA                (deploy:www-data 0755)
/etc/letsencrypt/live/<domain>/    certificates
```

Code is owned by `deploy` (so rsync needs no root) and group-readable by the
service account (so the service can import it but never write to it).

Python comes from `uv`, not from apt — noble ships 3.12 and the project needs
3.13. `uv` is pinned in `group_vars/all.yml` and installs the interpreter into
`/opt/uv-python`.

---

## Services

```bash
systemctl status tlsrep-backend      # app host
systemctl status tlsrep-proxy        # exit nodes
journalctl -u tlsrep-backend -f
```

Both units are hardened: dedicated non-login system user, `NoNewPrivileges`,
`PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, an empty capability
bounding set, a syscall filter, and an empty `ReadWritePaths` — neither service
writes to disk at all. State lives in PostgreSQL; logs go to the journal.

If you add a feature that needs to write a file, add exactly that path to
`ReadWritePaths=` in the unit template. Do not relax `ProtectSystem`.

---

## Firewall

`common` sets UFW to deny inbound / allow outbound and permits SSH. Roles open
what they need:

- app host: 80 and 443 (nginx role)
- exit nodes: the configured `tlsrep_proxy_listen_port` only, with 80 and 443
  explicitly denied — these are collectors and must not be reachable as web
  servers

To restrict who can use a collector, set `tlsrep_proxy_allowed_sources` in
`group_vars/tlsrep_proxy/main.yml` to a list of CIDRs.

---

## Operational notes

**Restarts are handler-driven.** Nothing restarts unless something actually
changed. A no-op deploy touches no services.

**The schema migration runs before the restart.** `schema.sql` is applied as a
normal task while the restart is a handler, and handlers flush at the end of
the play — so the schema is always in place before new code serves traffic.
It uses `CREATE TABLE IF NOT EXISTS`, so reapplying it is a no-op; that is why
it is marked `changed_when: false`.

**Certificates renew themselves** via the packaged `certbot.timer`. A deploy
hook reloads nginx when a renewal lands.

**HSTS is set with `preload`.** Once submitted to the preload list, browsers
will refuse plain HTTP for this domain for a long time and removal is slow. Set
`tlsrep_hsts_preload: false` in the nginx role defaults if you are not ready to
commit.

**PostgreSQL runs with `synchronous_commit = off`.** Ingest is append-heavy and
the data is statistical samples, so trading a sub-second window of observations
for much lower fsync pressure is deliberate. Revisit if the database ever holds
something you cannot lose.
