"""Every shipped policy pack must load and validate (offline)."""

import glob
import os

import pytest

from veritas.policy import load_policy

POLICIES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "policies", "*.yaml")))


@pytest.mark.parametrize("path", POLICIES)
def test_policy_loads_and_validates(path):
    policy = load_policy(path)
    assert policy.name
    assert policy.checks
    # every check targets an artifact the policy actually produces
    for c in policy.checks:
        assert c.target in policy.produces


def test_there_are_at_least_two_policies():
    assert len(POLICIES) >= 2
