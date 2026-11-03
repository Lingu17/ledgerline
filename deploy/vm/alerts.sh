#!/usr/bin/env bash
# Alerts by email, run by the owner in Cloud Shell:   bash alerts.sh create you@example.com     |   bash alerts.sh undo
#
#   1. An uptime check on https://35-207-220-110.sslip.io/api/health every 5 minutes, and an email when it fails.
#   2. An email when the nightly backup fails (log line "ledgerline-backup.service: Failed").
#   3. An email when no off-server copy has been logged for 36 hours ("off-server copy" missing).
# 2 and 3 read the VM's logs, which reach Cloud Logging through the Google Ops Agent; if the agent is turned off
# (SERVER_STEPS step 3), only alert 1 works. Uptime checks and alerting fit in Cloud Monitoring's free allowance.
set -euo pipefail
PROJECT="${PROJECT:-project-0b143378-307b-4214-818}"
HOST=35-207-220-110.sslip.io
gcloud config set project "$PROJECT" >/dev/null

undo() {
  for p in $(gcloud alpha monitoring policies list --filter='displayName~"^Ledgerline:"' --format='value(name)'); do gcloud alpha monitoring policies delete "$p" --quiet; done
  for c in $(gcloud beta monitoring channels list --filter='displayName="Ledgerline owner email"' --format='value(name)'); do gcloud beta monitoring channels delete "$c" --quiet --force; done
  for u in $(gcloud monitoring uptime list-configs --filter='displayName="Ledgerline health"' --format='value(name)'); do gcloud monitoring uptime delete "$u" --quiet; done
  for m in ledgerline_backup_failed ledgerline_offsite_copy; do gcloud logging metrics delete "$m" --quiet 2>/dev/null || true; done
  echo "Ledgerline alerts removed."
}

create() {
  local email="${1:?your email address}" tmp; tmp=$(mktemp -d)
  CHANNEL=$(gcloud beta monitoring channels create --display-name="Ledgerline owner email" --type=email \
            --channel-labels=email_address="$email" --format='value(name)')
  gcloud monitoring uptime create "Ledgerline health" --resource-type=uptime-url \
    --resource-labels=host="$HOST",project_id="$PROJECT" --path=/api/health --protocol=https --period=5 --timeout=10
  CHECK=$(gcloud monitoring uptime list-configs --filter='displayName="Ledgerline health"' --format='value(name)' | sed 's#.*/##')
  gcloud logging metrics create ledgerline_backup_failed --description="Ledgerline nightly backup failed" \
    --log-filter='textPayload:"ledgerline-backup.service: Failed"'
  gcloud logging metrics create ledgerline_offsite_copy --description="Ledgerline off-server copy made" \
    --log-filter='textPayload:"off-server copy ledgerline/"'
  cat > "$tmp/uptime.json" <<EOF
{"displayName": "Ledgerline: site down", "combiner": "OR", "notificationChannels": ["$CHANNEL"],
 "conditions": [{"displayName": "health check failing", "conditionThreshold": {
   "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"$CHECK\" AND resource.type=\"uptime_url\"",
   "aggregations": [{"alignmentPeriod": "600s", "perSeriesAligner": "ALIGN_NEXT_OLDER", "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.host"]}],
   "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "600s", "trigger": {"count": 1}}}]}
EOF
  cat > "$tmp/backup_failed.json" <<EOF
{"displayName": "Ledgerline: backup failed", "combiner": "OR", "notificationChannels": ["$CHANNEL"],
 "conditions": [{"displayName": "backup unit failed", "conditionThreshold": {
   "filter": "metric.type=\"logging.googleapis.com/user/ledgerline_backup_failed\" AND resource.type=\"gce_instance\"",
   "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_COUNT"}],
   "comparison": "COMPARISON_GT", "thresholdValue": 0, "duration": "0s", "trigger": {"count": 1}}}]}
EOF
  cat > "$tmp/offsite_missing.json" <<EOF
{"displayName": "Ledgerline: no off-server copy for 36 hours", "combiner": "OR", "notificationChannels": ["$CHANNEL"],
 "conditions": [{"displayName": "no off-server copy logged", "conditionAbsent": {
   "filter": "metric.type=\"logging.googleapis.com/user/ledgerline_offsite_copy\" AND resource.type=\"gce_instance\"",
   "aggregations": [{"alignmentPeriod": "3600s", "perSeriesAligner": "ALIGN_COUNT"}],
   "duration": "129600s", "trigger": {"count": 1}}}]}
EOF
  for f in uptime backup_failed offsite_missing; do gcloud alpha monitoring policies create --policy-from-file="$tmp/$f.json" >/dev/null; done
  rm -rf "$tmp"
  echo "Created: uptime check, email channel, 3 alert policies. Google sends a confirmation to $email only if required."
  echo "Check: Cloud Console > Monitoring > Alerting shows three 'Ledgerline:' policies. Undo: bash alerts.sh undo"
}

case "${1:-}" in
  create) create "${2:-}" ;;
  undo) undo ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
