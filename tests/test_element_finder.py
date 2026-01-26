"""Tests for element finder module."""

import pytest
from executor.element_finder import get_target_variations


class TestGetTargetVariations:
    """Tests for get_target_variations function."""

    def test_single_suffix(self):
        """Test stripping a single suffix."""
        variations = get_target_variations("Submit button")
        assert variations == ["Submit button", "Submit"]

    def test_multiple_suffixes(self):
        """Test recursive suffix stripping."""
        variations = get_target_variations("Password input field")
        assert variations == ["Password input field", "Password input", "Password"]

    def test_no_suffix(self):
        """Test target without suffix."""
        variations = get_target_variations("Username")
        assert variations == ["Username"]

    def test_link_suffix(self):
        """Test stripping link suffix."""
        variations = get_target_variations("credentials link")
        assert variations == ["credentials link", "credentials"]

    def test_empty_target(self):
        """Test empty target."""
        variations = get_target_variations("")
        assert variations == []

    def test_case_insensitive(self):
        """Test case-insensitive suffix matching."""
        variations = get_target_variations("Login BUTTON")
        assert variations == ["Login BUTTON", "Login"]

    def test_btn_suffix(self):
        """Test btn abbreviation suffix."""
        variations = get_target_variations("Submit btn")
        assert variations == ["Submit btn", "Submit"]

    def test_preserves_case(self):
        """Test that original case is preserved in variations."""
        variations = get_target_variations("PASSWORD Field")
        assert variations == ["PASSWORD Field", "PASSWORD"]
