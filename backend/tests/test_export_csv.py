"""A company's records as CSV in one zip: every table, readable by a spreadsheet, no formulas run, nothing secret."""
import csv
import io
import zipfile

from ledgerline import export_csv

from .test_saas import _invite_and_join


def unzip(r):
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_the_export_has_every_table_with_headers_and_rows(client):
    for step in ("deposits", "links", "agents"):
        client.post("/api/demo/step", json={"step": step})
    r = client.get("/api/export/csv")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith(f'attachment; filename="ledgerline-{client.org_id}-')
    z = unzip(r)
    assert sorted(z.namelist()) == sorted([f"{n}.csv" for n in export_csv.table_names()] + ["README.txt"])
    payments = list(csv.DictReader(io.StringIO(z.read("payments.csv").decode("utf-8-sig"))))
    assert {p["id"] for p in payments} >= {"DEP-1001", "DEP-1005"} and "amount_minor" in payments[0]
    audit = list(csv.DictReader(io.StringIO(z.read("audit_log.csv").decode("utf-8-sig"))))
    assert len(audit) > 10 and all(a["hash"] for a in audit)
    assert "inputs" not in z.read("plans.csv").decode("utf-8-sig").splitlines()[0]  # stored plan inputs stay out


def test_a_cell_a_spreadsheet_would_run_is_neutralised(client):
    client.post("/api/customers", json={"name": "=HYPERLINK(\"http://x\")", "country": "GB", "payer_names": ["ACME"],
                                        "refund_beneficiary": "+44 acct"})
    rows = list(csv.DictReader(io.StringIO(unzip(client.get("/api/export/csv")).read("customers.csv").decode("utf-8-sig"))))
    row = next(r for r in rows if "HYPERLINK" in r["name"])
    assert row["name"].startswith("'=") and row["refund_beneficiary"].startswith("'+")


def test_a_viewer_may_export(client, app):
    viewer = _invite_and_join(client, app, "reader@northbeam.test", "viewer")
    assert viewer.get("/api/export/csv").status_code == 200
