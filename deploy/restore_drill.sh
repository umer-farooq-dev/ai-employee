#!/bin/sh
# SEC-10 / ENGR-08: backup restore drill. Restores a dump into a scratch database next to the live one, checks it and
# prints the time taken (compare with the RTO). Never touches the live database.
#   sh deploy/restore_drill.sh <compose file> [dump file]     # no dump file: takes a fresh one first
# Example (production stack):  sh deploy/restore_drill.sh deploy/docker-compose.prod.yml
set -eu
COMPOSE="docker compose -f ${1:?compose file}"
DUMP="${2:-}"
DRILL_DB=restore_drill
start=$(date +%s)

if [ -z "$DUMP" ]; then
  DUMP="backups/drill-$(date +%Y%m%d-%H%M).dump"
  mkdir -p backups
  $COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DUMP"
fi
echo "dump: $DUMP ($(du -h "$DUMP" | cut -f1))"

$COMPOSE exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists $DRILL_DB && createdb -U \"\$POSTGRES_USER\" $DRILL_DB"
$COMPOSE exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $DRILL_DB --no-owner --exit-on-error" < "$DUMP"
restored=$(date +%s)

# same tables, same row counts for the main business tables, migrations complete, row-level security still on
check() { $COMPOSE exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d $1 -At -c \"$2\""; }
Q="SELECT (SELECT count(*) FROM information_schema.tables WHERE table_schema='public') || ' tables, ' ||
   (SELECT count(*) FROM tenancy_company) || ' companies, ' || (SELECT count(*) FROM crm_lead) || ' leads, ' ||
   (SELECT count(*) FROM billing_invoice) || ' invoices, ' || (SELECT count(*) FROM django_migrations) || ' migrations, ' ||
   (SELECT count(*) FROM pg_class WHERE relrowsecurity) || ' RLS tables'"
live=$(check "\$POSTGRES_DB" "$Q")
drill=$(check $DRILL_DB "$Q")
echo "live:     $live"
echo "restored: $drill"
$COMPOSE exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" $DRILL_DB"
end=$(date +%s)
echo "restore took $((restored - start)) s, whole drill $((end - start)) s"
if [ "$live" = "$drill" ]; then echo "RESULT: PASS"; else echo "RESULT: FAIL (counts differ; was the live database written during the drill?)"; exit 1; fi
