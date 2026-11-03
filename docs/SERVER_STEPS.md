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
off-server copy has been made for 36 hours. The last two read the VM's logs through the Google Ops Agent, so they need
the agent running (step 3). Undo: `bash alerts.sh undo`. Uptime checks and alerts fit in the free allowance.

## 6. Recovery drill: how long a full restore takes (Cloud Shell, about 20 minutes, once)

This proves the off-server copy can bring the whole service back on a new machine, and measures how long it takes.
It uses a temporary VM with no web access (no http tags), so the restored data is never public, and deletes it after.

On your computer, make a bundle of the code and upload it and `deploy/vm/restore_drill.sh` to Cloud Shell:

```bash
git bundle create ledgerline.bundle main
```

In Cloud Shell (put the backup key from your password manager in `backup.key` first):

```bash
ZONE=asia-south1-a
gcloud compute instances create ledgerline-drill --zone=$ZONE --machine-type=e2-small --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud
LATEST=$(gcloud storage ls gs://$BUCKET/ledgerline/ | sort | tail -1); gcloud storage cp "$LATEST" .
gcloud compute scp ledgerline.bundle restore_drill.sh "$(basename "$LATEST")" backup.key ledgerline-drill:~ --zone=$ZONE
gcloud compute ssh ledgerline-drill --zone=$ZONE --command "sudo bash restore_drill.sh ledgerline.bundle $(basename "$LATEST") backup.key main"
gcloud compute instances delete ledgerline-drill --zone=$ZONE --quiet
rm -f backup.key "$(basename "$LATEST")" ledgerline.bundle
```

The drill ends with `restore check: PASS` and `RECOVERY TIME: N minutes`. Send that line so the docs can state the
measured time. Saved Airwallex keys are not in the backup (by design); a real recovery reconnects Airwallex under
Settings, and moves the reserved address to the new VM.
