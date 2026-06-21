"""Shared fixtures for live tests (all require --live).

Target lists previously loaded from `config/targets/*.yml` are no longer
exposed as fixtures — monitored targets now live in the `monitored_system`
Postgres table (see CLAUDE.md). Tests that need the live target catalog
should hit `/sd/<type>` on the exporter instead.
"""
import pytest
import yaml
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


@pytest.fixture(scope="session")
def exporter_config_live():
    path = os.path.join(PROJECT_ROOT, "monitor_exporter", "config.yml")
    with open(path) as f:
        return yaml.safe_load(f)
