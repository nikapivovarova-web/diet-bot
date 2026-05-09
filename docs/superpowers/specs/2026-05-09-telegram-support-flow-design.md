# Telegram Support Flow Design

## Goal

Users need an obvious way to contact FoodBalance support from the bot, especially for payment issues. The support team needs enough context to diagnose a problem without asking the user to manually send their chat id, payment type, subscription status, or remaining limits.

## User Experience

Add a `🛟 Техподдержка` button:

- In the public start menu, directly below the promo-code button.
- In the subscriber cabinet, below `Изменить анкету`.

When the user taps the button, the bot starts a short support-request mode and asks the user to describe the issue in one message. The prompt should mention payment examples such as card/SberPay and Telegram Stars.

The next non-command message from that user becomes the support request. After sending it, the bot confirms that the request was sent and returns the normal menu for that chat.

## Admin Delivery

The bot sends the support request to the service support chat configured by `DIET_BOT_SUPPORT_CHAT_ID`.

The forwarded admin message includes:

- Request text.
- Chat id.
- Telegram user id, username, and display name when available.
- Current timestamp.
- Subscription/free-trial status from the existing entitlement state.
- Remaining monthly and extra attempts.
- Whether a saved questionnaire/profile exists.

The request should be sent as a new bot message, not as a Telegram forward, so the support team receives a structured diagnostic block even when the user message has no useful metadata.

## Configuration

`DIET_BOT_SUPPORT_CHAT_ID` is optional at startup.

If it is missing or invalid, the bot should still show the support button, but when a user submits a request it should say that support is temporarily not configured and ask them to try again later. The bot should not lose normal navigation state.

## Architecture

Keep the MVP inside `telegram_app.py` because the existing Telegram UI, subscription state, and message routing already live there.

Add:

- Support button text and callback constants.
- A per-chat in-memory `SUPPORT_REQUEST_CHAT_IDS` set for the active "next message is a support request" state.
- A helper to build the support prompt.
- A helper to format the admin diagnostic message.
- A helper to send the request to the configured support chat and handle Telegram API errors.

`handle_callback` should route the support callback into support-request mode. `handle_answer` should check support-request mode before normal free-text questionnaire handling, while still allowing slash commands to behave normally.

## Error Handling

If delivery to the support chat fails, the user gets a short retry-later message and the bot returns to the normal menu. This keeps users out of a stuck support state.

Slash commands such as `/start`, `/plan`, `/cancel`, `/myid`, and the admin command continue to be processed normally even if the chat was waiting for a support request.

## Testing

Add focused tests for:

- Public start keyboard includes `Техподдержка` below promo code.
- Subscriber cabinet includes `Техподдержка`.
- Tapping the support callback starts support-request mode and sends the prompt.
- A support message is delivered to the configured support chat with user and entitlement context.
- Missing support chat configuration produces a user-facing error and exits support mode.
- Existing promo, features, subscription, and ration buttons keep their current callbacks.
