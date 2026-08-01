"""Tests for the payload-shaping helpers."""

from __future__ import annotations

import json

from cisco_sdwan_mcp.sdwan.formatting import (
    build_query,
    count_by,
    envelope,
    match_device,
    project,
    string_rule,
    truncate,
)


def test_project_keeps_only_requested_fields():
    records = [{"a": 1, "b": 2, "c": 3}]

    assert project(records, ("a", "c")) == [{"a": 1, "c": 3}]


def test_project_drops_absent_and_null_fields():
    records = [{"a": 1, "b": None}]

    assert project(records, ("a", "b", "missing")) == [{"a": 1}]


def test_project_detailed_returns_everything():
    records = [{"a": 1, "b": 2}]

    assert project(records, ("a",), detailed=True) == records


def test_truncate_reports_whether_it_cut():
    rows = [{"n": i} for i in range(5)]

    assert truncate(rows, 10) == (rows, False)
    assert truncate(rows, 2) == (rows[:2], True)


def test_envelope_reports_total_alongside_returned():
    rows = [{"n": i} for i in range(5)]

    result = envelope(rows, limit=2, window_hours=24)

    assert result["count"] == 5
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert result["window_hours"] == 24
    assert "Raise `limit`" in result["note"]


def test_envelope_omits_truncation_note_when_complete():
    result = envelope([{"n": 1}], limit=10)

    assert result["count"] == 1
    assert "truncated" not in result
    assert "note" not in result


def test_build_query_encodes_the_lookback_window():
    query = json.loads(build_query(hours=24, size=100))

    assert query["size"] == 100
    rule = query["query"]["rules"][0]
    assert rule["field"] == "entry_time"
    assert rule["operator"] == "last_n_hours"
    assert rule["value"] == ["24"]


def test_build_query_combines_rules_with_and():
    query = json.loads(
        build_query(hours=6, rules=[string_rule("severity", ["critical"])])
    )

    assert query["query"]["condition"] == "AND"
    assert len(query["query"]["rules"]) == 2
    assert query["query"]["rules"][1] == {
        "value": ["critical"], "field": "severity", "type": "string", "operator": "in"
    }


def test_build_query_without_filters_is_empty():
    assert json.loads(build_query()) == {}


def test_count_by_sorts_by_descending_count():
    records = [{"s": "up"}, {"s": "down"}, {"s": "up"}, {"s": "up"}]

    assert count_by(records, "s") == {"up": 3, "down": 1}


def test_count_by_labels_missing_values_unknown():
    assert count_by([{"other": 1}], "s") == {"unknown": 1}


def test_match_device_accepts_hostname_system_ip_or_chassis():
    record = {"host-name": "BR1-EDGE1", "system-ip": "10.0.0.11",
              "chasisNumber": "C8K-AAAA-0001"}

    assert match_device(record, "BR1-EDGE1")
    assert match_device(record, "br1-edge1")  # case-insensitive
    assert match_device(record, " 10.0.0.11 ")  # tolerates whitespace
    assert match_device(record, "C8K-AAAA-0001")
    assert not match_device(record, "BR2-EDGE1")
    assert not match_device(record, "")


def test_match_device_requires_a_full_match():
    """A prefix must not match, or 'BR1' would silently select 'BR10'."""
    assert not match_device({"host-name": "BR10-EDGE1"}, "BR1")
