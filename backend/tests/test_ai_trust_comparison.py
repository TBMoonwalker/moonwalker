"""Offline comparison protocol, causality, label and execution regressions."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from service import ai_trust_comparison as comparison

NAMES = ["qwen3:8b", "clef:latest", "clef-flash:latest"]


def sample(index: int = 0) -> dict[str, Any]:
    features = {
        "schema_version": "1",
        "source_event": "entry_preflight",
        "symbol": "BTC/USDC",
        "event_timestamp": f"2026-01-{index + 1:02d}T00:00:00Z",
        "position": {"entry_price": 100.0, "entry_amount": 1},
        "market_context": {"has_market_context": True, "latest_close": 99.0},
    }
    return {
        "id": str(index),
        "deal_id": "deal-" + str(index),
        "features": features,
        "provenance": {
            "source": "audited_entry_capture_v1",
            "feature_sha256": comparison.fingerprint(features),
            "captured_at": features["event_timestamp"],
            "decision_at": features["event_timestamp"],
            "latest_information_at": features["event_timestamp"],
            "evidence": "capture-log record 123",
        },
        "outcome": {
            "status": "closed",
            "profit": 1.0,
            "duration_hours": 24,
            "so_count": 0,
        },
    }


def answer_body() -> dict[str, Any]:
    questions = comparison.systemone_request(NAMES[1], {})["questions"]
    answers = {}
    for name, question in questions.items():
        criteria = question["criteria"]
        if question["type"] == "score":
            answers[name] = {
                "type": "score",
                "score": 1.0,
                "confidence": 1.0,
                "probabilities": {str(i): float(i == 1) for i in range(5)},
                "legend": {str(i): text for i, text in enumerate(criteria)},
            }
        else:
            choice = "none" if name == "severity" else "no"
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": 1.0,
                "probabilities": {key: float(key == choice) for key in criteria},
            }
    return {"model": NAMES[1], "answers": answers}


def test_causal_features_are_frozen_and_outcomes_separate() -> None:
    raw = sample()
    original = copy.deepcopy(raw)
    validated = comparison.validate_sample(raw)
    payload = comparison.systemone_request(NAMES[1], validated["features"])
    assert payload["state"] == raw["features"]
    assert "outcome" not in payload and "provenance" not in payload
    assert len(payload["questions"]) == 7
    validated["features"]["position"]["entry_price"] = 0
    assert raw == original


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda row: row.pop("provenance"), "missing_provenance"),
        (
            lambda row: row["provenance"].update(feature_sha256="wrong"),
            "provenance_hash_mismatch",
        ),
        (
            lambda row: row["provenance"].update(
                latest_information_at="2026-02-01T00:00:00Z"
            ),
            "post_entry_information",
        ),
        (
            lambda row: row["provenance"].update(captured_at="2026-02-01T00:00:00Z"),
            "post_entry_information",
        ),
        (lambda row: row["features"].update(source_event="open_deal"), "not_pre_entry"),
        (
            lambda row: row["features"].update(outcome_profit=9),
            "unknown_feature_fields",
        ),
        (
            lambda row: row["features"]["market_context"].update(api_key="secret"),
            "unknown_feature_fields",
        ),
        (
            lambda row: row["features"]["position"].update(entry_price=float("nan")),
            "invalid_feature_value",
        ),
        (
            lambda row: row["provenance"].update(decision_at="2026-01-01"),
            "invalid_timestamp",
        ),
    ],
)
def test_invalid_provenance_and_payloads_rejected(change: Any, reason: str) -> None:
    row = sample()
    change(row)
    with pytest.raises(comparison.ComparisonError, match=reason):
        comparison.validate_sample(row)


@pytest.mark.parametrize(
    "profit,hours,count,expected",
    [
        (1, 71.999, 2, False),
        (0, 1, 0, True),
        (-1, 1, 0, True),
        (1, 72, 0, True),
        (1, 1, 3, True),
    ],
)
def test_composite_label_boundaries(
    profit: float, hours: float, count: int, expected: bool
) -> None:
    label = comparison.outcome_label(
        {
            "status": "closed",
            "profit": profit,
            "duration_hours": hours,
            "so_count": count,
        }
    )
    assert label is not None and label["bad_entry"] is expected


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        {"status": "open"},
        {"status": "blocked"},
        {"status": "closed", "profit": None, "duration_hours": 1, "so_count": 0},
        {"status": "closed", "profit": 1, "duration_hours": 1, "so_count": 0.5},
    ],
)
def test_missing_outcomes_are_not_negative_profit(outcome: Any) -> None:
    assert comparison.outcome_label(outcome) is None


def test_native_score_keeps_concentration_separate() -> None:
    result = comparison.validate_systemone(answer_body(), NAMES[1])
    assert result["native_score"] == 1.0
    assert result["confidence"] == 1.0
    assert result["would_warn"] is False
    assert "risk_score" not in result


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update(model="wrong"),
        lambda body: body["answers"].pop("warning"),
        lambda body: body["answers"]["risk"].update(score=float("nan")),
        lambda body: body["answers"]["risk"].update(score=4),
        lambda body: body["answers"]["risk"].update(confidence=2),
        lambda body: body["answers"]["risk"]["probabilities"].pop("4"),
        lambda body: body["answers"]["risk"]["probabilities"].update({"0": -1}),
        lambda body: body["answers"]["risk"].update(legend={}),
        lambda body: body["answers"]["warning"].update(choice="unknown"),
        lambda body: body["answers"]["severity"].update(
            choice="high", probabilities={"none": 0, "low": 0, "medium": 0, "high": 1}
        ),
    ],
)
def test_invalid_systemone_is_not_clamped_or_scored(mutate: Any) -> None:
    body = answer_body()
    mutate(body)
    with pytest.raises(comparison.ComparisonError):
        comparison.validate_systemone(body, NAMES[1])


async def fake_models(_: str, names: list[str]) -> tuple[str, list[dict[str, Any]]]:
    return "0.35.1", [
        {
            "name": name,
            "digest": "digest-" + name,
            "api": "chat" if i == 0 else "systemone",
        }
        for i, name in enumerate(names)
    ]


@pytest.mark.asyncio
async def test_dry_run_and_empty_input_never_contact_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden(*_: Any) -> None:
        raise AssertionError("Unexpected provider request")

    monkeypatch.setattr(comparison, "provider_models", forbidden)
    monkeypatch.setattr(comparison, "provider_assessment", forbidden)
    report = await comparison.run_comparison(
        [sample()], tmp_path / "dry", "http://localhost:11434", NAMES
    )
    assert report["attempts"] == 0
    assert report["status"] == "insufficient_data"
    empty = await comparison.run_comparison(
        [{}], tmp_path / "empty", "http://localhost:11434", NAMES, execute=True
    )
    assert empty["eligible_inputs"] == 0 and empty["attempts"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [1, 30, 33])
async def test_serial_cap_no_retry_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: int
) -> None:
    monkeypatch.setattr(comparison, "provider_models", fake_models)
    calls, active, maximum = [], 0, 0

    async def assess(
        _: str, model: dict[str, Any], features: dict[str, Any]
    ) -> dict[str, Any]:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        calls.append((model["name"], features["event_timestamp"]))
        await asyncio.sleep(0)
        active -= 1
        if len(calls) == 1:
            raise httpx.ConnectError("unavailable")
        return {"would_warn": False}

    monkeypatch.setattr(comparison, "provider_assessment", assess)
    inputs = [sample(i) for i in range(12)]
    output = tmp_path / "run"
    first = await comparison.run_comparison(
        inputs,
        output,
        "http://localhost:11434",
        NAMES,
        execute=True,
        attempt_budget=budget,
    )
    assert len(calls) == first["attempts"] == budget
    assert len(set(calls)) == budget and maximum == 1
    assert first["models"][NAMES[0]]["statuses"]["provider_error"] == 1
    again = await comparison.run_comparison(
        inputs,
        output,
        "http://localhost:11434",
        NAMES,
        execute=True,
        resume=True,
        attempt_budget=budget,
    )
    assert again == first and len(calls) == budget
    inputs[0]["outcome"]["profit"] = -1
    with pytest.raises(comparison.ComparisonError, match="identical"):
        await comparison.run_comparison(
            inputs,
            output,
            "http://localhost:11434",
            NAMES,
            execute=True,
            resume=True,
            attempt_budget=budget,
        )


@pytest.mark.asyncio
async def test_cache_hit_does_not_charge_budget_or_fresh_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparison, "provider_models", fake_models)
    calls = []

    async def assess(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"would_warn": False}

    monkeypatch.setattr(comparison, "provider_assessment", assess)
    duplicate = sample()
    duplicate["id"], duplicate["deal_id"] = "duplicate", "other-deal"
    report = await comparison.run_comparison(
        [sample(), duplicate], tmp_path, "http://localhost:11434", NAMES, execute=True
    )
    assert report["attempts"] == len(calls) == 3
    assert all(
        len(row["fresh_attempt_durations_seconds"]) == 1
        for row in report["models"].values()
    )
    events = [
        json.loads(line)
        for line in (tmp_path / "results.jsonl").read_text().splitlines()
    ]
    assert sum(event.get("result", {}).get("cached", False) for event in events) == 3


@pytest.mark.asyncio
async def test_cancelled_attempt_consumes_slot_and_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparison, "provider_models", fake_models)
    calls = []

    async def interrupted(_: str, model: dict[str, Any], __: Any) -> dict[str, Any]:
        calls.append(model["name"])
        if len(calls) == 1:
            raise asyncio.CancelledError
        return {"would_warn": False}

    monkeypatch.setattr(comparison, "provider_assessment", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await comparison.run_comparison(
            [sample()], tmp_path, "http://localhost:11434", NAMES, execute=True
        )
    # An incomplete final JSONL line is discarded, but the durable reservation stays.
    with (tmp_path / "results.jsonl").open("a") as stream:
        stream.write('{"partial":')
    report = await comparison.run_comparison(
        [sample()], tmp_path, "http://localhost:11434", NAMES, execute=True, resume=True
    )
    assert calls == NAMES
    assert report["attempts"] == 3
    assert report["models"][NAMES[0]]["statuses"] == {"interrupted": 1}


@pytest.mark.asyncio
async def test_total_deadline_and_no_timeout_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparison, "provider_models", fake_models)
    monkeypatch.setattr(comparison, "DEADLINE_SECONDS", 0.005)
    calls = []

    async def stall(*args: Any) -> dict[str, Any]:
        calls.append(args)
        await asyncio.sleep(10)
        return {"would_warn": False}

    monkeypatch.setattr(comparison, "provider_assessment", stall)
    report = await comparison.run_comparison(
        [sample()], tmp_path, "http://localhost:11434", NAMES, execute=True
    )
    assert report["attempts"] == len(calls) == 3
    assert all(row["statuses"] == {"timeout": 1} for row in report["models"].values())


def test_paired_holdout_and_missing_outcome_denominators() -> None:
    samples = [comparison.validate_sample(sample(i)) for i in range(5)]
    samples[-1]["outcome"]["profit"] = -1
    models = [{"name": name} for name in NAMES]
    results = {
        comparison.fingerprint([row["id"], model]): {
            "status": "scored",
            "assessment": {"would_warn": row["id"] == "4"},
        }
        for row in samples
        for model in NAMES
    }
    report = comparison.build_report(samples, models, results, {}, 15)
    assert report["paired_cohort_ids"] == {
        "tuning": ["0", "1", "2"],
        "evaluation": ["3", "4"],
    }
    for model in report["models"].values():
        assert model["metrics"]["evaluation"]["bad_entry"] == {
            "tp": 1,
            "fp": 0,
            "fn": 0,
            "tn": 1,
            "n": 2,
            "warning_hit_rate": 1,
            "bad_entry_capture_rate": 1,
            "false_warning_rate": 0,
        }
    results[comparison.fingerprint(["4", NAMES[1]])] = {"status": "schema_invalid"}
    samples[3]["outcome"]["profit"] = None
    report = comparison.build_report(samples, models, results, {}, 15)
    assert report["status"] == "insufficient_data"
    assert report["unknown_outcomes"] == 1
    assert report["paired_cohort_ids"]["evaluation"] == []


@pytest.mark.asyncio
async def test_adapter_preserves_baseline_request_and_one_systemone_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import service.ai_trust as baseline

    captured = []

    async def post(
        url: str, *, json: dict[str, Any], timeout_seconds: float
    ) -> httpx.Response:
        captured.append((url, json, timeout_seconds))
        body = (
            answer_body()
            if url.endswith("systemone")
            else {
                "message": {
                    "content": '{"risk_score":25,"confidence":0.5,"would_warn":false,"warning_severity":"none","reason_codes":[],"operator_note":"Normal"}'
                }
            }
        )
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(comparison.ai_provider_client, "post", post)
    config = baseline.AiTrustConfig(True, False, "http://provider", NAMES[0], 60000, 0)
    features = sample()["features"]
    expected = await baseline._call_ollama(config, features)
    assert (
        await comparison.provider_assessment(
            "http://provider", {"name": NAMES[0], "api": "chat"}, features
        )
        == expected
    )
    assert captured[0] == captured[1]
    await comparison.provider_assessment(
        "http://provider", {"name": NAMES[1], "api": "systemone"}, features
    )
    assert len(captured) == 3
    assert captured[-1][0].endswith("/v1/systemone")
    assert captured[-1][1] == comparison.systemone_request(NAMES[1], features)


@pytest.mark.asyncio
async def test_digest_change_cannot_become_success_or_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = 0

    async def changing(base: str, names: list[str]) -> tuple[str, list[dict[str, Any]]]:
        nonlocal reads
        reads += 1
        version, models = await fake_models(base, names)
        if reads > 1:
            models[0]["digest"] = "changed"
        return version, models

    async def assess(*_: Any) -> dict[str, Any]:
        return {"would_warn": False}

    monkeypatch.setattr(comparison, "provider_models", changing)
    monkeypatch.setattr(comparison, "provider_assessment", assess)
    report = await comparison.run_comparison(
        [sample()], tmp_path, "http://provider", NAMES, execute=True
    )
    assert report["paired_cohort_ids"]["evaluation"] == []
    assert all(
        row["statuses"] == {"schema_invalid": 1} for row in report["models"].values()
    )
    events = [
        json.loads(line)
        for line in (tmp_path / "results.jsonl").read_text().splitlines()
    ]
    assert all(
        event["result"]["error_code"] == "model_identity_changed"
        for event in events
        if event["event"] == "result"
    )


@pytest.mark.asyncio
async def test_completed_corruption_and_symlink_outputs_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparison, "provider_models", fake_models)

    async def assess(*_: Any) -> dict[str, Any]:
        return {"would_warn": False}

    monkeypatch.setattr(comparison, "provider_assessment", assess)
    await comparison.run_comparison(
        [sample()], tmp_path / "run", "http://provider", NAMES, execute=True
    )
    journal = tmp_path / "run" / "results.jsonl"
    journal.write_text(journal.read_text().replace('"scored"', '"forged"', 1))
    with pytest.raises(comparison.ComparisonError, match="checksum"):
        await comparison.run_comparison(
            [sample()],
            tmp_path / "run",
            "http://provider",
            NAMES,
            execute=True,
            resume=True,
        )
    target = tmp_path / "do-not-touch"
    target.write_text("unchanged")
    (tmp_path / "unsafe").mkdir()
    (tmp_path / "unsafe" / "manifest.json.tmp").symlink_to(target)
    with pytest.raises(comparison.ComparisonError, match="symlinks"):
        await comparison.run_comparison(
            [], tmp_path / "unsafe", "http://provider", NAMES
        )
    assert target.read_text() == "unchanged"


def test_temporal_groups_do_not_leak_deals_or_identical_inputs() -> None:
    rows = [comparison.validate_sample(sample(i)) for i in range(5)]
    rows[4]["deal_id"] = rows[0]["deal_id"]
    partitions = comparison._partitions(rows)
    assert partitions[rows[0]["deal_id"]] == "excluded_overlap"
    rows[4]["deal_id"] = "last-deal"
    rows[4]["input_hash"] = rows[0]["input_hash"]
    partitions = comparison._partitions(rows)
    assert (
        partitions["last-deal"] == partitions[rows[0]["deal_id"]] == "excluded_overlap"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["old_version", "missing_model", "missing_digest"])
async def test_metadata_probe_is_read_only_and_checks_readiness(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    seen = []
    original_client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/version":
            return httpx.Response(
                200, json={"version": "0.34.0" if bad == "old_version" else "0.35.1"}
            )
        installed = [{"name": name, "digest": "digest-" + name} for name in NAMES]
        if bad == "missing_model":
            installed.pop()
        if bad == "missing_digest":
            installed[0].pop("digest")
        return httpx.Response(200, json={"models": installed})

    monkeypatch.setattr(
        comparison.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    with pytest.raises(comparison.ComparisonError):
        await comparison.provider_models("http://provider", NAMES)
    assert len(seen) == 2 and all(request.method == "GET" for request in seen)


@pytest.mark.asyncio
async def test_same_run_has_one_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparison, "provider_models", fake_models)
    entered, release = asyncio.Event(), asyncio.Event()

    async def assess(*_: Any) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return {"would_warn": False}

    monkeypatch.setattr(comparison, "provider_assessment", assess)
    task = asyncio.create_task(
        comparison.run_comparison(
            [sample()], tmp_path, "http://provider", NAMES, execute=True
        )
    )
    await entered.wait()
    try:
        with pytest.raises(BlockingIOError):
            await comparison.run_comparison(
                [sample()],
                tmp_path,
                "http://provider",
                NAMES,
                execute=True,
                resume=True,
            )
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_cancellation_waits_for_durable_write_before_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparison, "provider_models", fake_models)
    original_append = comparison._append
    writing, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def blocked_append(path: Path, event: dict[str, Any]) -> None:
        if event["event"] == "reserved":
            loop.call_soon_threadsafe(writing.set)
            assert release.wait(timeout=5)
        original_append(path, event)

    monkeypatch.setattr(comparison, "_append", blocked_append)
    task = asyncio.create_task(
        comparison.run_comparison(
            [sample()], tmp_path, "http://provider", NAMES, execute=True
        )
    )
    await writing.wait()
    task.cancel()
    try:
        with pytest.raises(BlockingIOError):
            await comparison.run_comparison(
                [sample()],
                tmp_path,
                "http://provider",
                NAMES,
                execute=True,
                resume=True,
            )
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(comparison._journal(tmp_path / "results.jsonl")) == 1


def recommendation_fixture() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    """Build 120 held-out independent entries with balanced known outcomes."""
    samples = []
    for i in range(400):
        raw = sample()
        raw.update(id=str(i), deal_id=f"deal-{i}")
        timestamp = str(1_700_000_000_000 + i * 60_000)
        raw["features"]["event_timestamp"] = timestamp
        for field in ("captured_at", "decision_at", "latest_information_at"):
            raw["provenance"][field] = timestamp
        raw["provenance"]["feature_sha256"] = comparison.fingerprint(raw["features"])
        raw["outcome"]["profit"] = -1 if i % 2 else 1
        samples.append(comparison.validate_sample(raw))
    models = [{"name": name} for name in NAMES]
    results = {
        comparison.fingerprint([row["id"], name]): {
            "status": "scored",
            "assessment": {"would_warn": bool(int(row["id"]) % 2)},
        }
        for row in samples
        for name in NAMES
    }
    return samples, models, results


def test_recommendation_names_clear_winner_and_explains_errors() -> None:
    samples, models, results = recommendation_fixture()
    for row in samples[280:]:
        for name in (NAMES[0], NAMES[2]):
            results[comparison.fingerprint([row["id"], name])]["assessment"][
                "would_warn"
            ] = False
    report = comparison.build_report(samples, models, results, {}, 1200, 1200)
    recommendation = report["recommendation"]
    assert report["status"] == "recommended"
    assert recommendation["model"] == NAMES[1]
    assert recommendation["evaluation_entries"] == 120
    assert f"Use {NAMES[1]}" in report["conclusion"]
    assert recommendation["evaluation_metrics"][NAMES[1]]["fn"] == 0
    assert report["attempt_cap"] == 1200


@pytest.mark.parametrize(
    "case", ["tie", "failure", "small_effect", "tradeoff", "duplicate"]
)
def test_recommendation_refuses_unproven_or_biased_winner(case: str) -> None:
    samples, models, results = recommendation_fixture()
    if case in {"small_effect", "tradeoff"}:
        for row in samples[280:]:
            i = int(row["id"])
            for name in (NAMES[0], NAMES[2]):
                if case == "tradeoff" or i == 281:
                    results[comparison.fingerprint([row["id"], name])]["assessment"][
                        "would_warn"
                    ] = False
        if case == "tradeoff":
            results[comparison.fingerprint(["280", NAMES[1]])]["assessment"][
                "would_warn"
            ] = True
    elif case == "failure":
        results[comparison.fingerprint(["399", NAMES[1]])] = {"status": "timeout"}
    elif case == "duplicate":
        samples[-1]["input_hash"] = samples[-2]["input_hash"]
    report = comparison.build_report(samples, models, results, {}, 1200)
    assert report["recommendation"]["model"] is None
    assert "No " in report["conclusion"]
    if case == "failure":
        assert report["recommendation"]["status"] == "incomplete_evaluation"


def test_paired_error_test_known_values_and_symmetry() -> None:
    assert comparison._paired_error_p_value(0, 0) == 1
    assert comparison._paired_error_p_value(10, 0) == pytest.approx(2 / 1024)
    assert comparison._paired_error_p_value(0, 10) == pytest.approx(2 / 1024)
    assert comparison._paired_error_p_value(100, 100) == pytest.approx(1)


@pytest.mark.asyncio
async def test_explicit_budget_is_pinned_on_resume(tmp_path: Path) -> None:
    output = tmp_path / "larger-run"
    report = await comparison.run_comparison(
        [sample()], output, "http://localhost:11434", NAMES, attempt_budget=1200
    )
    assert report["attempt_cap"] == 1200
    assert json.loads((output / "manifest.json").read_text())["max_attempts"] == 1200
    with pytest.raises(comparison.ComparisonError, match="identical"):
        await comparison.run_comparison(
            [sample()],
            output,
            "http://localhost:11434",
            NAMES,
            attempt_budget=30,
            resume=True,
        )
    with pytest.raises(comparison.ComparisonError, match="budget"):
        await comparison.run_comparison(
            [],
            tmp_path / "invalid",
            "http://localhost:11434",
            NAMES,
            attempt_budget=3001,
        )
