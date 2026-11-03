"""A slice of the randomized accuracy harness, run on every test pass (the full run is scripts/accuracy_run.py)."""
import pytest

from ledgerline.api.app import create_app
from ledgerline.config import load_settings

from .accuracy_harness import Scenario, run_sample_walkthrough


@pytest.fixture(scope="module")
def shared_app(tmp_path_factory):
    return create_app(load_settings({
        "LEDGERLINE_DATA_DIR": str(tmp_path_factory.mktemp("accuracy")), "LEDGERLINE_SIGNUP_PER_IP_HOUR": "100000", "LEDGERLINE_SIGNUP_PER_IP_DAY": "100000", "LEDGERLINE_SIGNUP_PER_DAY": "100000", # synthetic volume, not sign-ups
        "LEDGERLINE_PAYER_MCP_TRANSPORT": "memory",
        "ANTHROPIC_API_KEY": "", "AIRWALLEX_CLIENT_ID": "", "AIRWALLEX_API_KEY": "", "GOOGLE_CLIENT_ID": "", "APPLE_CLIENT_ID": "",
    }))


@pytest.mark.parametrize("seed", range(1001, 1013))
def test_random_company_matches_reference_model(shared_app, seed):
    Scenario(shared_app, seed).run()


def test_sample_walkthrough_is_deterministic(shared_app):
    a, b = run_sample_walkthrough(shared_app, 0), run_sample_walkthrough(shared_app, 1)
    assert a["deposits"] == b["deposits"]
    assert a["score"]["ledger_balanced"] and a["score"]["double_payments"] == 0 and a["score"]["deposits"] == 6
