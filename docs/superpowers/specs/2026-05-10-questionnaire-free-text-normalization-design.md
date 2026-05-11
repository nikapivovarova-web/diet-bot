# Questionnaire Free-Text Normalization Design

## Goal

Keep the questionnaire UX flexible while preventing unbounded free-text answers from entering profile storage and safety filters. The bot should save compact, normalized lists instead of raw user text for allergies, intolerances, excluded foods, and medical conditions.

## Scope

The change applies to questionnaire answers before profile creation, saved profile serialization, and legacy profile loading from JSON or PostgreSQL JSONB. It does not add a new UI flow or replace free-text input with buttons.

## Normalization Rules

Food-related list fields use one shared normalizer:

- raw answer length limit: 300 characters;
- maximum items: 12;
- item length: 2 to 40 characters;
- separators: comma, semicolon, and newline;
- normalization: trim, lowercase, replace `ё` with `е`, collapse whitespace, strip punctuation around items, remove unsupported symbols, deduplicate while preserving order.

If an answer is too long or contains more than 12 valid items, the questionnaire returns a validation error and asks the user to shorten the list. It does not silently drop allergy, intolerance, condition, or excluded-food entries.

## Conditions

Medical conditions are stored only as recognized `ConditionCode` values. The condition normalizer maps known aliases such as diabetes, high blood pressure, gastritis, GERD, pregnancy, lactation, celiac disease, CKD, gout, dialysis, oncology, severe liver disease, and eating-disorder wording to existing enum codes.

Unrecognized condition text is not saved. If a condition answer contains no recognized conditions and is not a "none" answer, the questionnaire asks the user to rewrite the answer with short comma-separated terms.

## Data Flow

`QuestionnaireSession.receive()` validates and normalizes free-text fields before storing answers. `build_profile()` then creates `Restriction` objects from already-normalized item strings and condition codes from normalized condition values.

`_profile_to_dict()` continues to save compact `restrictions` and `conditions`; raw questionnaire answers are not serialized.

`_profile_from_dict()` migrates legacy profiles on read by sanitizing restriction values and condition values before constructing `UserProfile`. Invalid or oversized legacy list items are ignored so old state cannot keep bloating runtime memory.

## Testing

Tests cover splitting, whitespace cleanup, lowercasing, deduplication, length errors, item count errors, long item dropping, condition alias recognition, unrecognized condition rejection, and legacy profile migration from noisy saved data.
