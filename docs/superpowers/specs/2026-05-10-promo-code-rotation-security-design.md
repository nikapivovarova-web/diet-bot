# Promo Code Rotation Security Design

## Goal

Revoke the existing plaintext promo-code batch and issue 200 new monthly subscription promo codes without keeping usable codes in the bot runtime state.

## Approach

Runtime storage stores promo-code lookup keys, not bearer codes. A lookup key is `sha256:` plus the SHA-256 digest of the normalized promo code. Bot activation normalizes the user input, hashes it, and looks up the hash. Successful activation still returns the normalized code only in memory for the current request.

The old `.diet_bot_state/monthly_promo_codes.txt` export is removed. New plaintext codes are written only to an ignored one-time export under `exports/`, with Windows ACLs restricted to the current user when possible. That export remains sensitive and should not be deployed with the bot.

## Scope

- JSON promo state saves hashed lookup keys.
- PostgreSQL promo storage uses the same hashed lookup key in the existing `promo_codes.code` column.
- Promo activation, duplicate checks, and monthly subscription grants keep existing behavior.
- Entitlement charge IDs and PostgreSQL entitlement events use the hash reference instead of logging the raw code.
- Existing plaintext JSON promo files can still be parsed for migration, but the rotation replaces the live file with hashed records.

## Verification

Focused tests cover one-time JSON activation, absence of raw codes in saved JSON, hyphenless normalization, and PostgreSQL activation when a test database is configured.
