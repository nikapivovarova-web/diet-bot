# Free Trial Subscription Flow Design

## Goal

Make the Telegram bot easier to start and turn the free trial into a clear subscription funnel.

Users should not need to type `/start` manually. They should be able to open the Telegram command menu, choose `/start`, press "Попробовать бесплатно", complete the short questionnaire, and immediately receive a one-day trial ration. After the trial ration, the bot should explain that this was a free one-day sample and offer a monthly subscription.

## User Flow

1. When the bot starts, it registers Telegram bot commands:
   - `/start` - start or reopen the welcome screen.
   - `/plan` - start the ration questionnaire.
   - `/cancel` - reset the active questionnaire.
2. `/start` sends the existing welcome photo and welcome text with inline buttons.
3. Pressing "Попробовать бесплатно" starts the questionnaire.
4. After the questionnaire is complete, the bot generates and sends a one-day ration automatically.
5. After the ration messages, the bot sends a trial explanation and an "Оформить подписку" button.
6. Pressing "Оформить подписку" opens the existing subscription payment options.

## Trial Message

The message after a successful trial ration should be concise and sales-oriented without sounding pushy:

```text
Это пробный рацион на 1 день, чтобы вы могли увидеть, как работает FoodBalance.

В месячную подписку входят 4 недельных рациона и 5 дополнительных дневных рационов. Если рацион на какой-то день не подойдёт, вы сможете заменить его на другой.

Чтобы получать полноценные рационы, оформите доступ на месяц.
```

The button text should be:

```text
💳 Оформить подписку
```

## Behavior Changes

The current post-questionnaire choice between a one-day ration and a weekly PDF should no longer appear for the free trial path. The free trial path should always produce a one-day ration.

The existing weekly PDF flow can remain in the code for paid or future flows, but it should not be offered immediately after the free questionnaire.

The existing "Составить еще один рацион" after-plan button should be replaced by the subscription CTA for the trial result, so the user clearly understands that repeated access belongs to the paid plan.

## Implementation Notes

Add Telegram command registration in the bot startup path with `BotCommand` and `bot.set_my_commands`. This keeps the `/start` command available from Telegram's built-in menu.

Add a helper for the trial CTA keyboard. Reuse the existing `CALLBACK_SUBSCRIBE` callback so the new CTA opens the current subscription payment message.

Let `_send_plan` accept an optional reply markup for the final message. The trial path should pass the trial CTA keyboard; internal repeat or direct one-day plan paths can keep using the existing after-plan keyboard.

After questionnaire completion, call the one-day ration sender directly instead of `_send_calculation_options`.

## Testing

Update Telegram app tests to cover:

- Start keyboard still contains the welcome buttons.
- A new trial CTA keyboard contains the "Оформить подписку" button with `CALLBACK_SUBSCRIBE`.
- Questionnaire completion sends the calculation/ration flow directly and does not show the one-day/week choice keyboard.
- The trial message appears after a successful one-day ration.
- Bot startup registers `/start`, `/plan`, and `/cancel` commands.
