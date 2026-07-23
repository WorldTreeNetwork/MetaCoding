#!/usr/bin/env bash
# Rebuild the farmOS value-equivalence oracle from ctkr/ctkr/oracle/README.md.
set -euo pipefail
step() { echo "=== $* ==="; }

step "network"
docker network create farmos-oracle-net 2>/dev/null || echo "(network exists)"

step "db"
docker run -d --name farmos-oracle-db --network farmos-oracle-net \
  -e POSTGRES_USER=farm -e POSTGRES_PASSWORD=farm -e POSTGRES_DB=farm postgres:16

step "www"
docker run -d --name farmos-oracle-www --network farmos-oracle-net \
  -p 8095:80 farmos/farmos:4.x

step "wait for postgres"
for i in $(seq 1 60); do
  if docker exec farmos-oracle-db pg_isready -U farm -d farm >/dev/null 2>&1; then
    echo "postgres ready after ${i}s"; break
  fi
  sleep 1
done

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
