# Subscriber Cabinet Menu Design

## Goal

Active subscribers should not see the free-trial entry point as their main path. When a user already has an active subscription or active test access, the bot should show a compact subscriber cabinet with direct actions for the products included in the subscription.

## User Experience

For users without an active subscription, the existing start menu remains unchanged:

- Try free
- Monthly subscription
- Features
- Promo code

For active subscribers, `/start`, payment success, and post-generation navigation should show a working cabinet:

- Get a 1-day ration, with the remaining limit visible in the button
- Get a weekly ration PDF, with the remaining limit visible in the button
- Change questionnaire

The subscriber cabinet should not include upsell buttons for extra attempts or subscription purchase. Extra-purchase buttons stay only in the existing paywall flow when a relevant limit is exhausted.

## Limit Rules

Subscription and extra-attempt limits live only in the subscription entitlement state. Questionnaire/profile state is separate.

Changing the questionnaire must not reset, reduce, refresh, or otherwise mutate subscription limits. The bot should only spend a limit when the user requests a 1-day ration or weekly PDF and generation is allowed by access rules. If generation fails, the existing refund path should preserve the spent attempt.

If a subscriber taps a ration button before a profile is available in memory, the bot starts the questionnaire first. Completing the questionnaire should return the user to ration-type selection instead of consuming a limit just for changing or creating the profile.

## Architecture

Add a subscriber-aware start menu helper in `telegram_app.py`. It checks the current chat entitlement and returns the subscriber cabinet when subscription/test access is active; otherwise it returns the public start keyboard.

Keep generation callbacks unchanged in spirit:

- `diet:one_day` uses the saved profile if present, otherwise starts the questionnaire.
- `diet:week_pdf` uses the saved profile if present, otherwise starts the questionnaire.
- `diet:new` starts a fresh questionnaire and does not touch entitlement state.

After a questionnaire is completed outside the free-trial path, the bot should show the ration choice/cabinet so subscribers can choose the product they want without pressing the free-trial button.

## Testing

Add focused tests around Telegram UI helpers and entitlement isolation:

- Active subscriber start keyboard has no free-trial button and includes both ration buttons with limits.
- Subscriber cabinet includes the change-questionnaire action.
- Public start keyboard remains unchanged for non-subscribers.
- Starting or changing the questionnaire does not mutate stored subscription limits.
- Existing limit consumption and refund behavior remains covered by current subscription tests.
