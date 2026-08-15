# Security Policy

## Supported Versions

EasyOps is pre-1.0. Security fixes are applied only to the latest release
line. Older releases are not maintained.

| Version | Supported          |
|---------|--------------------|
| latest  | :white_check_mark: |
| < latest| :x:                |

## Reporting a Vulnerability

The EasyOps team treats security reports as the highest-priority work.
**Do not open public GitHub issues for security problems.**

Report vulnerabilities by one of the following private channels:

1. **GitHub Security Advisory** (preferred): use
   `Security` -> `Report a vulnerability` on the repository. This keeps the
   conversation private and allows the maintainers to request CVE IDs through
   GitHub.
2. **Encrypted email**: send a PGP-encrypted report to
   `security@easyops.local`. The current public key fingerprint is published
   in the release notes of the most recent release.

Please include the following information so we can reproduce and triage the
report quickly:

- Affected version (git tag or image tag).
- Component (API, Celery worker, frontend, deploy template, backup engine,
  CI workflow, dependency).
- Step-by-step reproduction, including any required host/container state.
- Observed impact and any proof of concept.
- Suggested fix or mitigation, if any.

### Disclosure timeline

| Stage                         | Target       |
|-------------------------------|--------------|
| Acknowledgement of receipt    | 1 business day |
| Initial triage and severity   | 5 business days |
| Fix or mitigation published   | 30 calendar days for high/critical severity, 90 calendar days otherwise |
| Public disclosure             | After a fix is released, or after 90 days if no fix path is agreed, whichever comes first |

Reporters are credited in the change record unless they request otherwise.

## Threat model boundaries

The following boundaries are explicit, documented design decisions and must
hold for any contribution that touches them. Each boundary is guard-railed by
contracts or regression tests; violations fail the CI gate.

- **SSH host-key pinning.** Every remote connection (inspection, deploy,
  restore) verifies the server's host key against the fingerprint stored on
  the `server_asset` row. A mismatched fingerprint aborts the connection.
  `SSH_ALLOW_UNVERIFIED_HOST_KEY` allows unverified connections **only** for
  local demonstration, is `false` by default, and must never be enabled in a
  shared or production deployment.
- **Credentials encrypted at rest, never in Celery/Redis.** Asset passwords
  and SSH private keys are Fernet-encrypted (key derived from
  `CREDENTIAL_ENCRYPTION_KEY`) before persistence. Workers decrypt them in
  memory only; credentials never appear in Celery messages, the Redis broker,
  task results, or audit rows.
- **Controlled batch execution.** Batch operations are limited to a fixed
  whitelist of operations (disk/memory/service/restart/log/port) whose
  parameters are validated against whitelist rules (regex whitelist) and
  shell-quoted with `shlex.quote`. Arbitrary command execution requires
  break-glass, is admin-only, and is audited with a stated reason.
- **Preview-before-write confirmation.** Write operations require a `preview`
  call that validates the command and returns a single-use `confirm_token`;
  the actual execution rejects requests without the matching token. Read
  operations are idempotency-keyed to prevent duplicate submission.
- **Deployment never executes project scripts.** Deployments render a compose
  document only from a fixed template; `build_script`/`deploy_script` content
  from the project repository is never executed. Steps are restricted to the
  whitelist `pull`/`build`/`up`/`healthcheck`/`rollback`.
- **Restore only from verified backups.** The backup/restore API restores
  only from records with `checksum_ok=1`; a failed or tampered backup can
  never clobber the last valid backup. Restores import into a fresh target
  database so the running system's tables are never dropped in place.
- **Secrets are never rendered by charts or images.** The Docker images do
  not bake secret values; operators must supply `SECRET_KEY`,
  `CREDENTIAL_ENCRYPTION_KEY`, database password and admin password through
  the Compose environment or an external secret manager. Git history and
  change records are scrubbed of real credentials (see
  [Desensitization](#desensitization) below).

## CI and supply-chain controls

The following controls are enforced by the GitHub Actions workflows
(`backend`, `frontend`, `deploy-check`):

- **Pull-request-only triggers.** `pull_request_target` and `secrets.*` are
  forbidden in CI workflows. CI never has write access to the repository on
  pull-request events.
- **Test gate.** Full `pytest` suite must pass. The suite includes whitelist
  rejection, token-confirmation, backup-failure-isolation and migration
  round-trip tests.
- **Coverage baseline.** Global coverage must stay ≥ 50%; the security core
  modules (`common`, `config`, `dependencies`, `services.ssh_service`) must
  stay ≥ 80%.
- **Static analysis.** `ruff check` must pass cleanly.
- **Dependency audit.** `pip-audit` must report no known vulnerabilities;
  problematic dependencies are upgraded (recorded in `CHANGELOG.md`).
- **Compose and Kubernetes validation.** `docker compose config` and a
  `kubeconform` schema check run on every change that touches deployment
  manifests.
- **Frontend build.** The Vue frontend must build cleanly (`npm run build`).
- **Verifiable releases.** Release artifacts ship with checksums; see the
  release notes for verification commands.

## Credential handling

- Asset credentials (password/private key) are encrypted at rest with Fernet
  using a SHA-256-derived key from `CREDENTIAL_ENCRYPTION_KEY`. See
  `easyops_api/common/crypto.py`.
- `SECRET_KEY` (JWT signing) and `CREDENTIAL_ENCRYPTION_KEY` must be provided
  by the operator; the image never generates or defaults them in production.
- Local secrets and the credential inventory live under `~/.easyops-lab/`,
  which is gitignored; the SSH private key there is restricted to the
  `easyops-lab` user and SSH password authentication is refused on lab hosts.
- Backup storage (`backup_data` volume) and loopback-only compose
  bindings keep credentials and backup payloads off the public network.

## Desensitization

- All evidence collected for acceptance (logs, screenshots, backup summaries,
  change records) is desensitized: real host IPs appear as hostnames or are
  replaced, SSH fingerprints are shown but no private material, and backup
  originals are never committed to Git.
- Contributors must never paste real tokens, private keys, or encrypted
  credential blobs into issues, PR descriptions, or change records.

## Security-conscious contribution checklist

Before opening a pull request that touches security-sensitive code, confirm:

- [ ] No new `pull_request_target` triggers are introduced.
- [ ] No new inline secret values, generated credentials, or `CHANGE_ME`
      defaults that could be applied by accident.
- [ ] SSH host-key verification is not weakened for new remote paths.
- [ ] New write endpoints require preview confirmation; new batch operations
      stay inside the whitelist.
- [ ] New dependencies are audited with `pip-audit` and added to the test
      coverage gates.
- [ ] New environment variables are documented in `.env.example` and the
      Compose env block (without secret values).
- [ ] Backup changes preserve the "verified-backup-only restore" and
      "fresh-database import" invariants.