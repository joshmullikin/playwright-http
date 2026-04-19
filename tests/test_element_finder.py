"""Tests for element finder module."""

import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from executor.element_finder import (
    find_by_aria_path,
    find_by_selector,
    find_clickable_element,
    find_element,
    find_input_element,
    get_target_variations,
)




def make_found_locator():
    """Return a locator mock that reports count=1."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=1)
    loc.first = MagicMock()
    return loc


def make_empty_locator():
    """Return a locator mock that reports count=0."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=0)
    loc.first = MagicMock()
    return loc


def make_page_with_modal(found_loc, use_modal=False):
    """Create a page mock; if use_modal=True, a visible dialog scope exists."""
    page = MagicMock()
    page.locator = MagicMock(return_value=make_empty_locator())
    page.get_by_role = MagicMock(return_value=make_empty_locator())
    page.get_by_text = MagicMock(return_value=make_empty_locator())
    page.get_by_label = MagicMock(return_value=make_empty_locator())
    page.get_by_placeholder = MagicMock(return_value=make_empty_locator())

    if use_modal:
        modal_loc = AsyncMock()
        modal_loc.count = AsyncMock(return_value=1)
        modal_loc.last = MagicMock()
        # Modal scope
        modal_scope = MagicMock()
        modal_scope.get_by_role = MagicMock(return_value=found_loc)
        modal_scope.get_by_text = MagicMock(return_value=make_empty_locator())
        modal_scope.get_by_label = MagicMock(return_value=make_empty_locator())
        modal_scope.get_by_placeholder = MagicMock(return_value=make_empty_locator())
        modal_scope.locator = MagicMock(return_value=make_empty_locator())
        modal_loc.last = modal_scope
        page.locator = MagicMock(side_effect=lambda sel, **kw: (
            modal_loc if "dialog" in sel else make_empty_locator()
        ))

    return page


class TestGetTargetVariations:
    """Tests for get_target_variations function."""

    def test_single_suffix(self):
        variations = get_target_variations("Submit button")
        assert variations == ["Submit button", "Submit"]

    def test_multiple_suffixes(self):
        variations = get_target_variations("Password input field")
        assert variations == ["Password input field", "Password input", "Password"]

    def test_no_suffix(self):
        variations = get_target_variations("Username")
        assert variations == ["Username"]

    def test_link_suffix(self):
        variations = get_target_variations("credentials link")
        assert variations == ["credentials link", "credentials"]

    def test_empty_target(self):
        variations = get_target_variations("")
        assert variations == []

    def test_case_insensitive(self):
        variations = get_target_variations("Login BUTTON")
        assert variations == ["Login BUTTON", "Login"]

    def test_btn_suffix(self):
        variations = get_target_variations("Submit btn")
        assert variations == ["Submit btn", "Submit"]

    def test_preserves_case(self):
        variations = get_target_variations("PASSWORD Field")
        assert variations == ["PASSWORD Field", "PASSWORD"]


class TestFindBySelector:
    """Tests for find_by_selector covering return locator.first (lines 110-111)."""

    async def test_returns_first_when_found(self):
        """When selector matches (count > 0), returns locator.first."""
        found_loc = make_found_locator()
        page = MagicMock()
        modal_loc = AsyncMock()
        modal_loc.count = AsyncMock(return_value=0)  # No modal visible

        page.locator = MagicMock(side_effect=lambda sel, **kw: (
            modal_loc if "dialog" in sel else found_loc
        ))

        result = await find_by_selector(page, "#submit-btn")
        assert result is found_loc.first

    async def test_returns_none_when_not_found(self):
        """When no match found, returns None."""
        page = MagicMock()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)

        result = await find_by_selector(page, "#nonexistent")
        assert result is None

    async def test_exception_caught_returns_none(self):
        """When locator raises, exception is caught and returns None."""
        page = MagicMock()
        bad_loc = AsyncMock()
        bad_loc.count = AsyncMock(side_effect=Exception("DOM error"))
        empty = make_empty_locator()

        page.locator = MagicMock(side_effect=lambda sel, **kw: (
            empty if "dialog" in sel else bad_loc
        ))

        result = await find_by_selector(page, "#bad-selector")
        assert result is None


class TestFindElement:
    """Tests for find_element covering _find_element_in return paths."""

    async def test_finds_by_role_button(self):
        """find_element finds button by role → return locator.first."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=found_loc)
        page.get_by_text = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)

        result = await find_element(page, "Submit")
        assert result is found_loc.first

    async def test_finds_by_text(self):
        """find_element finds via get_by_text → return locator.first."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=found_loc)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)

        result = await find_element(page, "Welcome message")
        assert result is found_loc.first

    async def test_finds_by_testid(self):
        """find_element finds via data-testid locator → return locator.first."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            if "testid" in sel:
                return found_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)

        result = await find_element(page, "submit")
        assert result is found_loc.first

    async def test_returns_none_if_not_found(self):
        """find_element returns None when nothing matches."""
        page = MagicMock()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)

        result = await find_element(page, "Nonexistent XYZ")
        assert result is None

    async def test_css_selector_delegates_to_find_by_selector(self):
        """CSS selector target calls find_by_selector path."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            return found_loc

        page.locator = MagicMock(side_effect=loc_se)

        result = await find_element(page, "#submit-button")
        assert result is found_loc.first


class TestFindInputElement:
    """Tests for find_input_element covering _find_input_in return paths."""

    def _make_page_returning_for(self, match_method: str):
        """Helper: page mock where only match_method locator returns count=1."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            if match_method == "locator" and ("name" in sel or "id" in sel):
                return found_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)

        if match_method == "role":
            page.get_by_role = MagicMock(return_value=found_loc)
        else:
            page.get_by_role = MagicMock(return_value=empty)

        if match_method == "label":
            page.get_by_label = MagicMock(return_value=found_loc)
        else:
            page.get_by_label = MagicMock(return_value=empty)

        if match_method == "placeholder":
            page.get_by_placeholder = MagicMock(return_value=found_loc)
        else:
            page.get_by_placeholder = MagicMock(return_value=empty)

        page.get_by_text = MagicMock(return_value=empty)
        return page, found_loc

    async def test_finds_by_role_textbox(self):
        """find_input_element returns locator.first via role=textbox."""
        page, found_loc = self._make_page_returning_for("role")
        result = await find_input_element(page, "Email")
        assert result is found_loc.first

    async def test_finds_by_label(self):
        """find_input_element returns locator.first via get_by_label."""
        page, found_loc = self._make_page_returning_for("label")
        result = await find_input_element(page, "Email Address")
        assert result is found_loc.first

    async def test_finds_by_placeholder(self):
        """find_input_element returns locator.first via get_by_placeholder."""
        page, found_loc = self._make_page_returning_for("placeholder")
        result = await find_input_element(page, "Enter email")
        assert result is found_loc.first

    async def test_finds_by_name_attribute(self):
        """find_input_element returns locator.first via input[name*=...] locator."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            if "name" in sel and "input" in sel:
                return found_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        result = await find_input_element(page, "username")
        assert result is found_loc.first

    async def test_finds_by_id_attribute(self):
        """find_input_element returns locator.first via input[id*=...] locator."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        call_count = [0]
        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            call_count[0] += 1
            # First name locator (count 1+2) returns empty, then id locator returns found
            if "id" in sel and "input" in sel:
                return found_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        result = await find_input_element(page, "password")
        assert result is found_loc.first

    async def test_returns_none_when_nothing_found(self):
        """find_input_element returns None when nothing matches."""
        page = MagicMock()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        result = await find_input_element(page, "nonexistent field abc")
        assert result is None


class TestFindClickableElement:
    """Tests for find_clickable_element covering _find_clickable_in return paths."""

    def _make_page_for(self, match_role: str | None = "button"):
        found_loc = make_found_locator()
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            return empty

        page.locator = MagicMock(side_effect=loc_se)

        def role_se(role, **kw):
            if role == match_role:
                return found_loc
            return empty

        page.get_by_role = MagicMock(side_effect=role_se if match_role else lambda r, **k: empty)
        page.get_by_text = MagicMock(return_value=empty if match_role else found_loc)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)
        return page, found_loc

    async def test_finds_button_role(self):
        """find_clickable_element returns locator.first via button role."""
        page, found_loc = self._make_page_for("button")
        result = await find_clickable_element(page, "Submit")
        assert result is found_loc.first

    async def test_finds_link_role(self):
        """find_clickable_element returns locator.first via link role."""
        page, found_loc = self._make_page_for("link")
        result = await find_clickable_element(page, "Home")
        assert result is found_loc.first

    async def test_finds_menuitem_role(self):
        """find_clickable_element returns locator.first via menuitem role."""
        page, found_loc = self._make_page_for("menuitem")
        result = await find_clickable_element(page, "File")
        assert result is found_loc.first

    async def test_finds_by_text_fallback(self):
        """find_clickable_element returns locator.first via get_by_text fallback."""
        page, found_loc = self._make_page_for(None)
        result = await find_clickable_element(page, "Go")
        assert result is found_loc.first

    async def test_returns_none_when_not_found(self):
        """find_clickable_element returns None when nothing matches."""
        page = MagicMock()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)

        result = await find_clickable_element(page, "nonexistent button xyz")
        assert result is None


class TestFindByAriaPath:
    """Tests for find_by_aria_path covering the return locator.first path (line 334)."""

    async def test_finds_exact_one_match(self):
        """When aria path resolves to count=1 locator, returns locator.first."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty_modal = AsyncMock()
        empty_modal.count = AsyncMock(return_value=0)

        def loc_se(sel, **kw):
            if "dialog" in sel:
                return empty_modal
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=found_loc)

        result = await find_by_aria_path(page, "button[name='Submit']")
        assert result is found_loc.first

    async def test_returns_none_when_multiple_matches(self):
        """When count != 1, returns None."""
        multi_loc = AsyncMock()
        multi_loc.count = AsyncMock(return_value=2)
        multi_loc.first = MagicMock()

        page = MagicMock()
        empty_modal = AsyncMock()
        empty_modal.count = AsyncMock(return_value=0)

        def loc_se(sel, **kw):
            if "dialog" in sel:
                return empty_modal
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=multi_loc)

        result = await find_by_aria_path(page, "button[name='Delete']")
        assert result is None

    async def test_returns_none_for_empty_path(self):
        """Empty aria_path → None immediately."""
        page = MagicMock()
        result = await find_by_aria_path(page, "")
        assert result is None

    async def test_chained_aria_path(self):
        """Multi-segment aria path chains locators correctly."""
        # listitem > button chain
        found_loc = make_found_locator()
        child_loc = AsyncMock()
        child_loc.count = AsyncMock(return_value=1)
        child_loc.first = MagicMock()
        child_loc.get_by_role = MagicMock(return_value=child_loc)

        found_loc.count = AsyncMock(return_value=1)
        found_loc.get_by_role = MagicMock(return_value=child_loc)

        page = MagicMock()
        empty_modal = AsyncMock()
        empty_modal.count = AsyncMock(return_value=0)

        def loc_se(sel, **kw):
            if "dialog" in sel:
                return empty_modal
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=found_loc)

        result = await find_by_aria_path(page, "listitem[name='Item 1'] > button[name='Delete']")
        assert result is child_loc.first

    async def test_returns_none_for_no_valid_segments(self):
        """When segments list is empty (e.g. aria_path=' > '), returns None (line 334)."""
        page = MagicMock()
        # " > " splits to [" ", " "] → both empty after strip → no valid segments
        result = await find_by_aria_path(page, " > ")
        assert result is None

    async def test_invalid_segment_format_breaks_inner_loop(self):
        """Segment that doesn't match regex → breaks inner loop → no return."""
        page = MagicMock()
        empty_modal = AsyncMock()
        empty_modal.count = AsyncMock(return_value=0)

        def loc_se(sel, **kw):
            if "dialog" in sel:
                return empty_modal
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=make_empty_locator())

        # "button[attr='value']" doesn't match the simple pattern (attr != name)
        result = await find_by_aria_path(page, "button[data-id='42']")
        assert result is None

    async def test_scope_exception_caught_continue(self):
        """When scope raises during aria parsing, except: continue (line 358-359)."""
        found_loc = make_found_locator()
        page = MagicMock()
        empty_modal = AsyncMock()
        empty_modal.count = AsyncMock(return_value=0)

        bad_loc = AsyncMock()
        bad_loc.count = AsyncMock(side_effect=Exception("scope error"))

        def loc_se(sel, **kw):
            if "dialog" in sel:
                return empty_modal
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=bad_loc)

        result = await find_by_aria_path(page, "button[name='Submit']")
        assert result is None


class TestFindElementExceptionPaths:
    """Tests for exception paths in _find_element_in and related functions."""

    async def test_testid_locator_raises_caught(self):
        """When testid locator raises, except Exception: pass covers lines 204-205."""
        page = MagicMock()
        empty = make_empty_locator()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            if "testid" in sel:
                raise Exception("locator failed")
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.get_by_label = MagicMock(return_value=empty)
        page.get_by_placeholder = MagicMock(return_value=empty)

        result = await find_element(page, "submit")
        assert result is None  # Exception caught, falls through

    async def test_input_locators_raise_covered(self):
        """When all locators raise in _find_input_in, all except handlers covered."""
        page = MagicMock()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            raise Exception("locator unavailable")

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(side_effect=Exception("role failed"))
        page.get_by_label = MagicMock(side_effect=Exception("label failed"))
        page.get_by_placeholder = MagicMock(side_effect=Exception("placeholder failed"))
        page.get_by_text = MagicMock(return_value=make_empty_locator())

        result = await find_input_element(page, "email")
        assert result is None

    async def test_clickable_locators_raise_covered(self):
        """When all role locators raise in _find_clickable_in, all except handlers covered."""
        page = MagicMock()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(side_effect=Exception("role unavailable"))
        page.get_by_text = MagicMock(return_value=make_empty_locator())
        page.get_by_label = MagicMock(return_value=make_empty_locator())
        page.get_by_placeholder = MagicMock(return_value=make_empty_locator())

        result = await find_clickable_element(page, "delete")
        assert result is None

    async def test_clickable_get_by_text_raises_covered(self):
        """When get_by_text raises in _find_clickable_in, except Exception: pass covered (404-405)."""
        page = MagicMock()

        def loc_se(sel, **kw):
            if "dialog" in sel:
                m = AsyncMock()
                m.count = AsyncMock(return_value=0)
                return m
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=make_empty_locator())
        page.get_by_text = MagicMock(side_effect=Exception("text locator failed"))
        page.get_by_label = MagicMock(return_value=make_empty_locator())
        page.get_by_placeholder = MagicMock(return_value=make_empty_locator())

        result = await find_clickable_element(page, "submit")
        assert result is None
