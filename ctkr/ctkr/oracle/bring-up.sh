#!/usr/bin/env bash
# Rebuild the farmOS value-equivalence oracle from ctkr/ctkr/oracle/README.md.
set -euo pipefail
step() { echo "=== $* ==="; }

# --- Pins and durable storage (2026-07-28) -----------------------------------
# WHY PINNED: `farmos/farmos:4.x` is a FLOATING tag. Every sealed pack in
# PACKS.jsonl asserts a fact about ONE farmOS build; a bring-up that silently
# lands on a newer 4.x makes those facts unfalsifiable — they would be compared
# against a source that no longer exists. The digest below is the build all 43
# packs were recorded against:
#
#   farmOS 4.0.4 · source commit 3fe0ce7e23de807be9b8bc97a211ce934327db39
#   (read out of the running oracle's /opt/drupal/composer.lock, 2026-07-28)
#
# The matching pristine source clone lives at the port workspace's source path
# (see MetaCoding-1gt). Override the pins only to deliberately move the oracle
# to a new farmOS, which is a re-baseline of every pack, not a bring-up.
#
# WHY NAMED VOLUMES: before this change the DB lived on an ANONYMOUS volume and
# the site lived in the container layer with no mounts at all — `docker rm` or a
# `system prune --volumes` destroyed the witness for every recorded pack, with
# nothing named to protect. Now the state a rebuild must not lose is addressable.
FARMOS_IMAGE="${FARMOS_IMAGE:-farmos/farmos@sha256:2c0ed3ed759f58b28c87b01be99ddc1dfbc509af3272721574b731a49c8afdd3}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres@sha256:33f923b05f64ca54ac4401c01126a6b92afe839a0aa0a52bc5aeb5cc958e5f20}"

step "pins"
echo "farmOS   : $FARMOS_IMAGE"
echo "postgres : $POSTGRES_IMAGE"

step "network"
docker network create farmos-oracle-net 2>/dev/null || echo "(network exists)"

step "volumes"
docker volume create farmos-oracle-db-data >/dev/null
docker volume create farmos-oracle-files   >/dev/null
docker volume create farmos-oracle-keys    >/dev/null

step "db"
docker run -d --name farmos-oracle-db --network farmos-oracle-net \
  -v farmos-oracle-db-data:/var/lib/postgresql/data \
  -e POSTGRES_USER=farm -e POSTGRES_PASSWORD=farm -e POSTGRES_DB=farm "$POSTGRES_IMAGE"

step "www"
docker run -d --name farmos-oracle-www --network farmos-oracle-net \
  -v farmos-oracle-files:/opt/drupal/web/sites/default/files \
  -v farmos-oracle-keys:/opt/drupal/keys \
  -p 8095:80 "$FARMOS_IMAGE"

step "wait for postgres"
# Gate on TCP, not the unix socket, and require the answer to hold. During
# initdb the entrypoint runs a temporary server with listen_addresses='' — it
# answers `pg_isready` on the socket, then SHUTS DOWN and restarts. The old
# socket-only check passed inside that window, so site-install raced ahead and
# died on "Connection refused" against a database that was mid-restart. An
# empty named volume makes initdb slower and the window wider, which is how a
# latent race became a reproducible failure.
ready=0
for i in $(seq 1 120); do
  if docker exec farmos-oracle-db pg_isready -h 127.0.0.1 -p 5432 -U farm -d farm >/dev/null 2>&1; then
    ready=$((ready + 1))
    if [ "$ready" -ge 3 ]; then echo "postgres accepting TCP after ${i}s"; break; fi
  else
    ready=0
  fi
  sleep 1
done
[ "$ready" -ge 3 ] || { echo "postgres never accepted TCP; aborting" >&2; exit 1; }

step "volume ownership"
# A named volume mounts in owned by root; farmOS runs as www-data. Without this
# `drush site-install` fails at the File system:Writable check ("The directory
# /sites/default/files/ is not writable") — the one thing the old anonymous-volume
# bring-up never hit, because it had no mounts to own.
docker exec -u root farmos-oracle-www sh -c \
  'mkdir -p /opt/drupal/web/sites/default/files /opt/drupal/keys && \
   chown -R www-data:www-data /opt/drupal/web/sites/default/files /opt/drupal/keys'

step "site-install (slow)"
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush site-install farm \
  --db-url=pgsql://farm:farm@farmos-oracle-db:5432/farm \
  --account-name=admin --account-pass=admin -y'

step "enable api modules"
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush en -y \
  farm_api farm_api_default_consumer farm_api_oauth simple_oauth_password_grant'

step "enable domain modules"
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush en -y \
  farm_land farm_animal farm_plant farm_harvest farm_seeding farm_input \
  farm_activity farm_observation farm_group farm_structure farm_quantity_standard \
  farm_inventory farm_birth farm_equipment farm_material farm_lab_test'
# farm_equipment:  without it POST /api/asset/equipment 404s — w0a's stock flows
#   hold inventory on equipment assets and cannot record on a fresh oracle.
# farm_inventory: without it `quantity--standard` has no inventory_adjustment /
#   inventory_asset and assets carry no `inventory` — the whole stock surface is
#   invisible at the boundary and every stock flow is unrunnable.
# farm_birth:     without it /api/log/birth 404s and no lineage flow can run.
# farm_material:  without it POST /api/asset/material 404s and the material
#   quantity_presave fold (MetaCoding-5ln) cannot fire — farm_quantity_material
#   arrives as a farm_input dependency, but the ASSET module owning the hook
#   does not.
# farm_lab_test:  without it /api/log/lab_test 404s and the lab_test identity
#   port (MetaCoding-wgy) cannot record. Enabling it pulls farm_lab,
#   farm_quantity_test, and farm_test_method as dependencies — the slice's
#   `test` quantity type and lab/test_method vocabularies ride in with them.

step "enable sensor module"
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush en -y farm_sensor'
# farm_sensor: without it POST /api/asset/sensor 404s and the sensor identity
#   port (MetaCoding-ej0) cannot record. Enabling it pulls data_stream as a
#   dependency — /api/data_stream/basic (the sensor's data_stream references)
#   rides in with it. Enabled on the live oracle 2026-07-23.

step "enable structure types"
docker exec farmos-oracle-www sh -c 'cd /opt/drupal && drush en -y farm_structure_types'
# farm_structure_types: base farm_structure ships only the 'other'
#   structure_type config entity; 'building' and 'greenhouse' live in this
#   submodule and 422 as invalid choices without it — the structure identity
#   port (MetaCoding-xq7) records all three. Enabled on the live oracle
#   2026-07-23.

step "oauth keys"
docker exec -u root farmos-oracle-www sh -c \
  'mkdir -p /opt/drupal/keys && chown www-data:www-data /opt/drupal/keys'
docker exec farmos-oracle-www sh -c \
  'cd /opt/drupal && drush simple-oauth:generate-keys /opt/drupal/keys'

step "health check: oauth token"
docker exec farmos-oracle-www sh -c \
  'curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost/oauth/token \
   -d "grant_type=password&client_id=farm&username=admin&password=admin"'

step "health check: json:api from host"
curl -s -o /dev/null -w "api %{http_code}\n" http://localhost:8095/api || true

echo "=== ORACLE UP ==="
