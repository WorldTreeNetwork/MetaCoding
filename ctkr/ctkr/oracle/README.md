# Value-equivalence oracle (port-loop Phase 2 — bead MetaCoding-04q)

Acceptance = **same value delivered, not same data model.** Source table
structures are historical cruft; a port that re-implements farmOS on an event
log + materialized views must deliver the same *values* at the domain boundary,
not the same rows. This package makes that testable.

See `docs/design/decomposition-schema.md` §5 (D4 Behavioral Scenarios, the
value-level rule) and `docs/design/port-loop-plan.md` Phase 2.

## What a semantic fixture is

A value-level given/when/then scenario in **domain-glossary terms**, storage-free
by rule (a fixture that names a table / column / id / SQL primitive is a defect
the storage-leak lint rejects):

```
given: a land asset "A"
when:  record a harvest log against A with a weight quantity of 5 kilogram
then:  A's yield_total (weight, kilogram) == 5
       A's harvest log_count == 1
```

No ids. No field names. The adapter mints real identities at run time; the
fixture never sees them. Each fixture carries provenance (the live observations
that produced it) and the glossary terms it uses.

## Pieces

| module | role |
|---|---|
| `glossary.py` | the closed domain vocabulary + storage-leak blacklist |
| `fixtures.py` | fixture schema, JSONL IO, validator + storage-leak lint |
| `adapter.py` | the per-implementation adapter contract (ABC) |
| `farmos_adapter.py` | live farmOS JSON:API adapter (OAuth2 password grant) |
| `recorder.py` | scripted value-flows → distilled fixtures (values from observation) |
| `runner.py` | verify fixtures against any adapter → pass/fail per fixture |

`data/core-pack/` is the recorded, SEALED core pack (7 fixtures);
`data/farmos_core_observations.jsonl` the raw request/response provenance.

## CLI

```bash
ctkr oracle-validate <fixtures.jsonl>                 # schema + storage-leak lint
ctkr oracle-record  --base-url http://localhost:8095  # record + distil from live farmOS
ctkr oracle-verify  <fixtures.jsonl> --adapter farmos # run against an implementation
```

Self-verification: recording the fixtures from live farmOS and re-running them
against the *same* farmOS must be 100% — a fixture that cannot reproduce against
its own source system is a bad distillation. This is the acceptance test of the
oracle itself.

## Bringing up a live farmOS (how the pack was recorded)

**One command:** `./bring-up.sh` (this directory) runs the whole sequence below and
ends with two health checks. It is idempotent on the network and volumes only —
remove any existing `farmos-oracle-db` / `farmos-oracle-www` containers first.
Rebuild takes ~2 min with the images cached.

### The pin (2026-07-28) — read this before rebuilding

The instance is ephemeral **by design**, and losing it costs nothing but the
rebuild — *provided the rebuild lands on the same farmOS*. Until 2026-07-28 it
could not promise that: the script ran `farmos/farmos:4.x`, a **floating tag**, so
a rebuild after an upstream push would have silently re-based every one of the 43
sealed packs onto a farmOS they were never recorded against, with no error
anywhere. Both images are now pinned by digest in `bring-up.sh`:

| | |
|---|---|
| farmOS | **4.0.4**, source `3fe0ce7e23de807be9b8bc97a211ce934327db39` |
| image | `farmos/farmos@sha256:2c0ed3ed759f58b28c87b01be99ddc1dfbc509af3272721574b731a49c8afdd3` |
| postgres | `postgres@sha256:33f923b05f64ca54ac4401c01126a6b92afe839a0aa0a52bc5aeb5cc958e5f20` |
| pristine source | `/Users/dukejones/work/WorldTree/farmos-src` @ that commit, read-only |

Moving the pin is a **re-baseline of every pack**, not a bring-up. Do it
deliberately, and re-record.

State now lives on three named volumes (`farmos-oracle-db-data`,
`farmos-oracle-files`, `farmos-oracle-keys`) rather than an anonymous volume and
the container layer, so `docker rm` no longer takes the witness with it.

**Verified 2026-07-28:** a from-scratch rebuild on the pinned digest re-recorded
the `last_gaps` pack to the **same five fixture ids** as the sealed pack
`9b49878b6b17` — identical `given`/`when`/`then`, i.e. every observed value
reproduced. The only deltas were fresh entity UUIDs and four extra POSTs, because
a clean oracle must create the `animal_type` / `unit` terms that the long-lived
one already had. That difference is itself the evidence that the packs do not
depend on accumulated oracle state.

After a rebuild, prove equivalence before recording anything new:

```bash
uv run python -m ctkr oracle-verify ctkr/oracle/data/core-pack/fixtures.jsonl \
  --adapter farmos --base-url http://localhost:8095   # must be 7/7
```

farmOS 4.x (Drupal 11.3, PHP 8.4) in Docker — a fresh, ephemeral instance:

```bash
docker network create farmos-oracle-net
docker run -d --name farmos-oracle-db --network farmos-oracle-net \
  -e POSTGRES_USER=farm -e POSTGRES_PASSWORD=farm -e POSTGRES_DB=farm postgres:16
docker run -d --name farmos-oracle-www --network farmos-oracle-net \
  -p 8095:80 farmos/farmos:4.x

# install the farm profile
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush site-install farm \
  --db-url=pgsql://farm:farm@farmos-oracle-db:5432/farm \
  --account-name=admin --account-pass=admin -y'

# enable the API (JSON:API + OAuth password grant + default `farm` consumer)
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush en -y \
  farm_api farm_api_default_consumer farm_api_oauth simple_oauth_password_grant'

# enable the domain modules that provide the asset/log/quantity bundles
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush en -y \
  farm_land farm_animal farm_plant farm_harvest farm_seeding farm_input \
  farm_activity farm_observation farm_group farm_structure farm_quantity_standard'

# generate the OAuth2 signing keys (dir must be writable by www-data)
docker exec -u root farmos-oracle-www sh -c \
  'mkdir -p /opt/drupal/keys && chown www-data:www-data /opt/drupal/keys'
docker exec farmos-oracle-www sh -c \
  'cd /opt/drupal && drush simple-oauth:generate-keys /opt/drupal/keys'
```

Auth is OAuth2 password grant against the public `farm` consumer (no client
secret, no scope): `POST /oauth/token` with
`grant_type=password&client_id=farm&username=admin&password=admin`.

### Bundle notes learned at the boundary

- `asset--land` requires `land_type`; only `other` is present on a bare install.
- `asset--animal` / `asset--plant` require an `*_type` taxonomy term (the adapter
  mints one on demand); `asset--group` is bare.
- `quantity--standard` value is a fraction field `{numerator, denominator}`;
  units are a `taxonomy_term--unit` relationship.
- `archived` on an asset is a **boolean** (not a timestamp); active == not archived.
- group membership is the group referenced by the latest done
  `is_group_assignment` activity log that includes the asset.
