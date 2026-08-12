"""Tests for the package version source-of-truth.

The version is declared once in ``cedrus.__version__`` and read at
build time via ``[tool.setuptools.dynamic] version``. These tests guard
against accidental drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import cedrus
from cedrus import __version__

_PEP_440 = re.compile(
    r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:[.\-](?:post|dev)\d+)?$"
)


def test_version_is_pep_440() -> None:
    assert _PEP_440.match(__version__), (
        f"cedrus.__version__={__version__!r} is not a PEP 440 release"
    )


def test_version_exposed_on_module() -> None:
    assert cedrus.__version__ == __version__


def test_pyproject_dynamic_version_attr_matches() -> None:
    """The build backend reads the version from ``cedrus.__version__``."""
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert "version =" in pyproject
    assert "cedrus.__version__" in pyproject


def test_changelog_has_unreleased_section() -> None:
    """``[Unreleased]`` must be present so contributors can add entries."""
    changelog = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
    assert "## [Unreleased]" in changelog
