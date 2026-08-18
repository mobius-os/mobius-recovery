from __future__ import annotations

from datetime import datetime, timedelta, timezone

from recovery_worker.chat import (
  MAX_TOOL_DETAIL_CHARS,
  _flush_assistant,
  _history,
  _provider_events,
  _record_provider_event,
  _tool_detail,
)
from recovery_worker.control import ExchangeResult
from recovery_worker.sessions import RecoverySession


def recovery_session() -> RecoverySession:
  now = datetime.now(timezone.utc)
  return RecoverySession(
    session_id="rec_test",
    exchange=ExchangeResult(
      "rec_test",
      "session-" + "x" * 48,
      now + timedelta(hours=1),
      now + timedelta(minutes=20),
      20 * 60,
    ),
  )


def test_claude_tool_input_is_emitted_only_when_complete() -> None:
  pending = {}
  started = _provider_events("claude", {
    "type": "stream_event",
    "event": {
      "type": "content_block_start",
      "index": 2,
      "content_block": {"type": "tool_use", "name": "Bash", "input": {}},
    },
  }, pending)
  delta = _provider_events("claude", {
    "type": "stream_event",
    "event": {
      "type": "content_block_delta",
      "index": 2,
      "delta": {
        "type": "input_json_delta",
        "partial_json": '{"command":"mobius-ssh -- id -u"}',
      },
    },
  }, pending)
  stopped = _provider_events("claude", {
    "type": "stream_event",
    "event": {"type": "content_block_stop", "index": 2},
  }, pending)

  assert started == []
  assert delta == []
  assert stopped == [{
    "type": "tool",
    "name": "Bash",
    "detail": "mobius-ssh -- id -u",
  }]
  assert pending == {}


def test_codex_command_event_has_a_bounded_human_readable_detail() -> None:
  events = _provider_events("codex", {
    "type": "item.completed",
    "item": {
      "type": "command_execution",
      "command": "mobius-ssh -- systemctl status mobius",
      "aggregated_output": "sensitive command output is not a tool summary",
    },
  }, {})

  assert events == [{
    "type": "tool",
    "name": "Command",
    "detail": "mobius-ssh -- systemctl status mobius",
  }]
  assert "sensitive command output" not in str(events)
  assert len(_tool_detail({"command": "x" * 5000})) == MAX_TOOL_DETAIL_CHARS


def test_tool_records_preserve_transcript_order_but_stay_out_of_model_history() -> None:
  session = recovery_session()
  session.add_message("user", "Check the service")
  segment: list[str] = []

  _record_provider_event(
    session, {"type": "text", "content": "I will inspect it."}, segment,
  )
  _record_provider_event(session, {
    "type": "tool",
    "name": "Bash",
    "detail": "mobius-ssh -- systemctl status mobius",
  }, segment)
  _record_provider_event(
    session, {"type": "text", "content": "The service is healthy."}, segment,
  )
  _flush_assistant(session, segment)

  messages = session.history()
  assert [(message.role, message.name) for message in messages] == [
    ("user", ""),
    ("assistant", ""),
    ("tool", "Bash"),
    ("assistant", ""),
  ]
  prompt = _history(session)
  assert "I will inspect it." in prompt
  assert "The service is healthy." in prompt
  assert "systemctl status" not in prompt
