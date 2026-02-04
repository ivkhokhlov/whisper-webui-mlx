RFC 0002: Single Telegram Completion Notification

Problem statement

The Telegram integration currently sends two messages per completed transcription: a plain text message "Transcription complete: <filename>" and a document message with the transcript file and the same caption. This duplicates notifications and leaves a standalone message without an attached file. The user wants exactly one Telegram message that includes the transcript file and only the filename as the visible text.

Motivation

Duplicate notifications are noisy and misleading, especially when the standalone text message appears without a file. Reducing this to a single message improves clarity, keeps the chat clean, and aligns the delivery with the user's expectation that the notification includes the transcript file and the original filename.

Goals

- Send exactly one Telegram message per completed job.
- The single message must include the transcript file attachment.
- The visible text must be only the original filename (no "Transcription complete:" prefix).

Non-goals

- Changing the transcript file name or content.
- Changing Telegram configuration, authentication, or delivery settings.
- Adding new notification channels or formatting beyond the filename caption.

Proposed design

- Remove the separate `send_telegram_message` call in `maybe_send_telegram`.
- Send only the document message via `send_telegram_document`.
- Set the document caption to `job.filename` (the original uploaded file name), with no additional prefix text.
- Keep existing error handling, configuration lookup, and result file existence checks unchanged.

External behavior / user-facing impact

- The Telegram chat receives a single message containing the transcript file, with the caption set to the original filename (e.g., `2026-01-30 12-16-40.mkv`).
- No standalone "Transcription complete" text message is sent.

APIs and interfaces

- No public API changes. Internal behavior of `maybe_send_telegram` changes to send one message instead of two.

Data model changes

- None.

Operational considerations

- No new configuration. Existing environment and settings file behavior remains the same.

Security and privacy considerations

- No change to what is sent; the transcript file and filename are already delivered today. This change only removes an extra message.

Implementation plan

1. Update `mlx_ui/telegram.py` to remove the `send_telegram_message` call.
2. Change the `send_telegram_document` caption to `job.filename` (no prefix).
3. Add or update a unit test covering Telegram message composition and ensuring only one request is made.
4. Run `make test` (or relevant subset) to validate.

Acceptance criteria

- Exactly one Telegram API request is issued per job completion when Telegram delivery is enabled.
- The Telegram message includes the transcript file attachment.
- The message caption equals the original filename with no "Transcription complete:" prefix.
- No standalone text-only message is sent.

Risks

- If any downstream automation relied on the separate text-only message, it will no longer be triggered. Mitigation: document the change and confirm no such dependency exists.

Open questions

- None.
