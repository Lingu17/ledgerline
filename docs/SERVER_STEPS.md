# Server steps for the owner

These change cloud and server security settings, so the owner runs them. Each step says how to check it and how to undo
it. Run them in this order. Never paste a key into a chat.

## 0. The new code must be live first (on the VM, 10 seconds)

The script, the new backup and its unit come from the deployed code. In your SSH window:

```bash
git -C /opt/ledgerline/src log --oneline -1
test -f /opt/ledgerline/src/deploy/vm/harden.sh && grep -q last_offsite /opt/ledgerline/src/deploy/vm/backup.py \
  && echo "OK: the code for these steps is live" || echo "STOP: deploy 2ce45c0 or later first"
```

Go on only if it prints OK.

## 1. Off-server backups (Cloud Shell, about 10 minutes, with a 1–2 minute restart of the VM)

Do this **now, well before 13 Nov**, never while judges may be looking: it stops the VM for a minute or two.

Open **Cloud Shell** from the Google Cloud Console, then run:

```bash
PROJECT=project-0b143378-307b-4214-818
ZONE=asia-south1-a
REGION=asia-south1
VM=ledgerline
BUCKET=ledgerline-backups-$(openssl rand -hex 4)
gcloud config set project $PROJECT

# FIRST: the site's address is its IP (35-207-220-110.sslip.io). If that IP is not reserved, stopping the VM would
# change it, and the site, its certificate and every link to it would stop working. Check it is reserved:
IP=$(gcloud compute instances describe $VM --zone=$ZONE --format='value(networkInterfaces[0].accessConfigs[0].natIP)')
RESERVED=$(gcloud compute addresses list --filter="address=$IP" --format='value(name)')
echo "VM address: $IP   reserved as: ${RESERVED:-NOT RESERVED}"
# If it says NOT RESERVED, reserve this exact address now (it stays on the running VM), then run the check again:
#   gcloud compute addresses create ledgerline-ip --addresses=$IP --region=$REGION
# Do not go on until the check prints a name instead of NOT RESERVED.

# A private bucket in another location than the VM (a multi-region in Asia), so one regional outage cannot take both
# copies: no public access, versions kept, everything deleted after 30 days.
gcloud storage buckets create gs://$BUCKET --location=asia --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$BUCKET --versioning
cat > lifecycle.json <<'EOF'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}},
          {"action": {"type": "Delete"}, "condition": {"daysSinceNoncurrentTime": 30}}]}
EOF
gcloud storage buckets update gs://$BUCKET --lifecycle-file=lifecycle.json

# A service account for the VM that can only add backup files to this bucket: not read, not delete, nothing else.
gcloud iam service-accounts create ledgerline-vm --display-name="Ledgerline VM"
SA=ledgerline-vm@$PROJECT.iam.gserviceaccount.com
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member=serviceAccount:$SA --role=roles/storage.objectCreator
# Let the Google Ops Agent keep writing logs and metrics under the new account. (If step 3 later turns the agent off,
# these two roles can be removed; the old account may have been failing exactly because it lacked them.)
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/logging.logWriter --condition=None
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/monitoring.metricWriter --condition=None

# Switch the VM to it. The VM must be stopped for this; the site is down for 1-2 minutes. This runs only if the
# address is reserved, so it keeps its address.
OLD_SA=$(gcloud compute instances describe $VM --zone=$ZONE --format='value(serviceAccounts[0].email)')
echo "Old service account (keep this to undo): $OLD_SA"
if [ -n "$(gcloud compute addresses list --filter="address=$IP" --format='value(name)')" ]; then
  gcloud compute instances stop $VM --zone=$ZONE &&
  gcloud compute instances set-service-account $VM --zone=$ZONE --service-account=$SA --scopes=cloud-platform &&
  gcloud compute instances start $VM --zone=$ZONE
else
  echo "STOP: $IP is not reserved; reserve it first (see above)."
fi
echo "Bucket: $BUCKET"
```

Why a new service account: the VM's current one is the project's default, which usually has the broad Editor role.
Giving it storage write would let the VM read and delete backups too. The new one can only create objects in this
bucket. Undo (another stop and start): `gcloud compute instances set-service-account $VM --zone=$ZONE
--service-account=$OLD_SA --scopes=devstorage.read_only,logging-write,monitoring-write,service-management,service-control,trace`.

Check the site is back: open https://35-207-220-110.sslip.io (same address; the certificate is unchanged).

Then on the VM (your own SSH window):

```bash
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh backup <the bucket name printed above>
```

It creates the backup key (once), runs one backup and shows `off-server copy ledgerline/<date>.tar.gz.enc`. It then
prints two commands. Run them in the same window and save each output as its own entry in your password manager:
`backup.key` decrypts the off-server copies, `connections.key` decrypts saved Airwallex keys. Without them, a copy
from the bucket cannot be read and Airwallex has to be connected again after a disk loss.

**Restore test (proves the copy and the saved key both work):** in the Cloud Console open the bucket, download the
newest `ledgerline/<date>.tar.gz.enc`, save the backup key from your password manager into a file, then from the
repository on your computer:

```bash
PYTHONPATH=backend backend/.venv/Scripts/python deploy/vm/restore_check.py <downloaded file> <key file>
```

It should end with `restore check: PASS`, listing each organization with `books balanced=True, audit chain ok=True`.
Then delete both the downloaded backup and the key file from your computer (and empty the recycle bin): together
they are a readable copy of every account's data.

## 2. Files and the app's sandbox (on the VM, about 15 minutes; the app restarts several times for a few seconds)

```bash
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh status     # before
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh files      # owner-only files
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh systemd    # sandbox, one group at a time
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh status     # after
```

After each change the script checks the app: health, a signed-out request refused with 401, and, under the same
sandbox, the payer-agent call, the signing and encryption libraries and an outbound HTTPS request. A group of settings
that breaks a check is taken back out and named as REMOVED. Send the output (it has no secrets) so the repository's
unit file can match what was kept. Undo: `harden.sh undo-systemd`, `harden.sh undo-files`.

## 3. Logs (on the VM, 2 minutes)

The backup alerts in step 5 read the VM's logs through the Google Ops Agent. Fixing the agent's log loop keeps all three alerts; turning the agent off leaves only the site-down alert.

```bash
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh journald       # cap the journal at 300 MB
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh opsagent-why   # what the Ops Agent keeps logging, after step 1
```

Run `opsagent-why` after step 1: the new service account's log and metric roles may be what stops the loop. Send its
output (it has no secrets). Only if the loop continues and you don't use Cloud Monitoring or Cloud Logging for this
VM, stop the agent with `harden.sh opsagent-off` (undo: `harden.sh opsagent-on`), and the two roles from step 1 can
then be removed.

## 4. SSH (on the VM, 2 minutes)

Keep your current SSH window open.

```bash
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh ssh
```

It turns off root login (after testing the configuration) and starts fail2ban for SSH. Open a **new** SSH connection
and check it works before closing the old one. Undo: `harden.sh undo-ssh`.

## 5. Email alerts (Cloud Shell, 3 minutes)

Upload `deploy/vm/alerts.sh` to Cloud Shell (⋮ → Upload), then:

```bash
bash alerts.sh create <your email>
```

You get an email when the site's health check fails for 10 minutes, when the nightly backup fails, and when no
off-server copy has been made for 23 hours. The last two read the VM's logs through the Google Ops Agent, so they need
the agent running (step 3). Undo: `bash alerts.sh undo`. Uptime checks and alerts fit in the free allowance.

## 6. Recovery drill: how long a full restore takes (Cloud Shell, about 20 minutes, once)

This proves the off-server copy can bring the whole service back on a new machine, and measures how long it takes.
It uses a temporary VM with no cloud identity (no service account) and no web server: Caddy is switched off and ports
80 and 443 stay closed, so the restored data is never public and the VM cannot read anything else in your project. It
still has an external address, which it needs to download packages (do not add `--no-address`). Background checks and
backups are off on it, so it never calls a customer's agent or a provider. It is deleted afterwards.

On your computer, bundle **the commit the live site runs** (the deploy branch, not `main`), with `HEAD` so the copy has
its files, and check it is the same commit as the `commit` field of https://35-207-220-110.sslip.io/api/health:

```bash
git fetch origin
git branch -f drill-src origin/deploy/vercel-render
git log --oneline -1 drill-src
git bundle create ledgerline.bundle HEAD drill-src
```

Upload `ledgerline.bundle`, `deploy/vm/restore_drill.sh` and `deploy/vm/backup.py` to Cloud Shell. In Cloud Shell, make the key file without leaving it readable (paste the backup key from your password
manager, press Enter, then Ctrl-D):

```bash
umask 077; cat > backup.key
```

Then save this as `drill.sh` in Cloud Shell and run `bash drill.sh`. It stops at the first failure, keeps the drill's
log, and removes the key, the backup and the bundle from Cloud Shell when it ends, however it ends:

```bash
set -euo pipefail
ZONE=asia-south1-a
BUCKET=$(gcloud storage buckets list --format='value(name)' --filter='name~^ledgerline-backups-')
echo "Bucket: ${BUCKET:-NOT FOUND}"; [ -n "$BUCKET" ] || exit 1
LATEST=$(gcloud storage ls "gs://$BUCKET/ledgerline/" | sort | tail -1)
[ -n "$LATEST" ] || { echo "STOP: no backup found in gs://$BUCKET/ledgerline/"; exit 1; }
FILE=$(basename "$LATEST")
trap 'rm -f backup.key "$FILE" ledgerline.bundle' EXIT
gcloud storage cp "$LATEST" .
# Check the key and the copy here, in seconds, before creating anything.
pip install --user -q cryptography
python3 - "$FILE" <<'PY'
import sys
from pathlib import Path
from backup import BackupRefused, decrypt, read_key
try:
    decrypt(Path(sys.argv[1]).read_bytes(), read_key(Path("backup.key")), "ledgerline/" + sys.argv[1])
except BackupRefused as exc:
    sys.exit(f"STOP: {exc}")
print("key and copy: OK")
PY
date
gcloud compute instances create ledgerline-drill --zone=$ZONE --machine-type=e2-small --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud --no-service-account --no-scopes
until gcloud compute ssh ledgerline-drill --zone=$ZONE --command true; do sleep 10; done   # wait until it accepts SSH
gcloud compute scp ledgerline.bundle restore_drill.sh "$FILE" backup.key ledgerline-drill:~ --zone=$ZONE
gcloud compute ssh ledgerline-drill --zone=$ZONE --command "sudo nohup bash restore_drill.sh ledgerline.bundle $FILE backup.key drill-src > drill.log 2>&1; tail -3 drill.log" || true
gcloud compute scp ledgerline-drill:~/drill.log . --zone=$ZONE
date
gcloud compute instances delete ledgerline-drill --zone=$ZONE --quiet
grep -E "restore check:|RECOVERY TIME" drill.log
```

The drill ends with `restore check: PASS` and `RECOVERY TIME: N minute(s)`, which counts from files on the new VM to a
healthy, verified Ledgerline. The two `date` lines give the whole time including the VM and the download. Send both
so the docs can state the measured times; `drill.log` has the full output. Saved Airwallex keys are not in the backup
(by design); a real recovery also reconnects Airwallex under Settings and moves the reserved address to the new VM.

## 7. Separate sending service (on the VM, 3 minutes; both services stop and start, a few seconds offline: run it well before judging)

After this step the Airwallex keys live only in a separate process; the app cannot read them. The server-wide
Airwallex keys move from `/etc/ledgerline/ledgerline.env` to a root-only `/etc/ledgerline/sender.env`, and
`connections.key` (which seals each company's own Airwallex keys) moves to `/var/lib/ledgerline-send/`, readable only by
the new `ledgerline-send` user. The app asks that service for money-out by id only (an approval, payment or quote id
and who pressed the button); the service re-runs the approval, expiry, pause, two-person and duplicate checks itself
against the company's database. It does not stop everything: a compromised app could still request a send that its
own database says was approved.

```bash
sudo bash /opt/ledgerline/src/deploy/vm/harden.sh sender
```

It ends with `sender: on.` after checking: both services active, the app's user cannot read `sender.env` or the moved
key, the app's settings hold no Airwallex key, and the app's user can reach the service. If any step or check fails it turns
itself back off. Turning off leaves owner-only files (600 and 700, `UMask=0077`) and puts the Airwallex lines at the end of `ledgerline.env`, whatever they were before. It refuses on a server that stores data in PostgreSQL, where the keys cannot be separated this way. While the service is on, `harden.sh files` refuses; run `sender-off` first. Undo: `harden.sh sender-off`. Run `sender-off` before ever deploying a commit older than this step; `update.sh` refuses such a commit (and a
rollback to one) while the service is on.
