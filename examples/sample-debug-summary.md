# duplicate invoice on retry

## Session
- Session ID: `2026-03-23_230501_duplicate-invoice-on-retry`
- Verdict: `fixed`

## Notes
- Reproduced only when the provider sends the same event ID twice.
- Root cause was missing idempotency validation in the retry path.

## Command Timeline
- `pytest tests/test_billing.py -k duplicate`
- `python scripts/replay_invoice.py failing_invoice.json`

## Follow-Up
- Convert replay flow into a permanent regression test.
