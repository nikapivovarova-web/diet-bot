from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field

from .domain import (
    ActivityLevel,
    ConditionCode,
    CookingTimePreference,
    Goal,
    Restriction,
    RestrictionType,
    Sex,
    UserProfile,
    normalize_text,
)
from .profile_normalization import (
    normalize_conditions,
    normalize_free_text_list,
    normalize_stored_condition_codes,
    normalize_stored_free_text_items,
)


SESSION_ID_ALPHABET = string.ascii_letters + string.digits
SESSION_ID_LENGTH = 8


def _new_session_id() -> str:
    return "".join(secrets.choice(SESSION_ID_ALPHABET) for _ in range(SESSION_ID_LENGTH))


@dataclass(frozen=True)
class Question:
    key: str
    prompt: str
    options: tuple[str, ...] = ()


QUESTIONS: tuple[Question, ...] = (
    Question("age", "🎂 Сколько вам лет? Бот составляет рацион только для взрослых 18+."),
    Question("sex", "Кто вы? 👇", ("👨 Мужчина", "👩 Женщина")),
    Question("height_cm", "📏 Ваш рост в сантиметрах? Например: 178."),
    Question("weight_kg", "⚖️ Ваш вес в килограммах? Например: 86 или 62,5."),
    Question("goal", "🎯 Какая цель?", ("⬇️ Похудение", "⚖️ Поддержание", "💪 Набор")),
    Question(
        "activity",
        "🏃 Выберите активность:\n"
        "🪑 Сидячая - в основном сидите, мало ходьбы, тренировок нет.\n"
        "🚶 Легкая - 5-7 тыс. шагов в день или 1-2 легкие тренировки в неделю.\n"
        "🏋️ Умеренная - 7-10 тыс. шагов или 3-4 тренировки в неделю.\n"
        "🔥 Высокая - 10-14 тыс. шагов или 4-5 интенсивных тренировок.\n"
        "⚡ Очень высокая - физическая работа, спорт почти каждый день или 15 тыс.+ шагов.",
        ("🪑 Сидячая", "🚶 Легкая", "🏋️ Умеренная", "🔥 Высокая", "⚡ Очень высокая"),
    ),
    Question("meal_count", "🍽️ Сколько приемов пищи в день вы хотите?", ("3", "4", "5")),
    Question(
        "cooking_time",
        "⏱️ Сколько времени вы готовы тратить на готовку в день?",
        ("до 15 минут", "15–30 минут", "более 30 минут"),
    ),
    Question(
        "allergies",
        "🚫 Есть аллергии на продукты? Перечислите через запятую или напишите 'нет'.",
        ("Нет",),
    ),
    Question(
        "intolerances",
        "🥛 Есть непереносимости? Например: лактоза, глютен. Если нет - напишите 'нет'.",
        ("Нет",),
    ),
    Question(
        "conditions",
        "🩺 Есть хронические заболевания или важные состояния? Например: целиакия, ХПН, диабет, гипертония. Если нет - напишите 'нет'.",
        ("Нет",),
    ),
    Question(
        "excluded_foods",
        "🙅 Какие продукты вы просто не едите? Через запятую или 'нет'.",
        ("Нет",),
    ),
)


@dataclass(frozen=True)
class QuestionnaireSession:
    answers: dict[str, str] = field(default_factory=dict)
    step_index: int = 0
    session_id: str = field(default_factory=_new_session_id)

    @property
    def is_complete(self) -> bool:
        return self.step_index >= len(QUESTIONS)

    @property
    def current_question(self) -> Question | None:
        if self.is_complete:
            return None
        return QUESTIONS[self.step_index]

    def receive(self, answer: str) -> tuple["QuestionnaireSession", str | None]:
        question = self.current_question
        if question is None:
            return self, None

        try:
            normalized_answer = _normalize_answer(question.key, answer)
        except ValueError as error:
            return self, str(error)

        next_answers = dict(self.answers)
        next_answers[question.key] = normalized_answer
        return QuestionnaireSession(next_answers, self.step_index + 1, self.session_id), None

    def should_stop_after_answer(self) -> str | None:
        age_answer = self.answers.get("age")
        if age_answer is None:
            return None
        try:
            age = int(_number(age_answer))
        except ValueError:
            return None
        if age < 18:
            return "Рационы составляются только для взрослых 18+. Лучше обсудить питание с родителями и врачом."
        return None

    def build_profile(self) -> UserProfile:
        if not self.is_complete:
            raise ValueError("Questionnaire is not complete.")

        restrictions = []
        restrictions.extend(
            Restriction(RestrictionType.ALLERGY, item)
            for item in _split_list(self.answers.get("allergies", ""))
        )
        restrictions.extend(_intolerance_restrictions(self.answers.get("intolerances", "")))
        restrictions.extend(
            Restriction(RestrictionType.EXCLUDED_FOOD, item)
            for item in _split_list(self.answers.get("excluded_foods", ""))
        )

        conditions = tuple(_parse_conditions(self.answers.get("conditions", "")))
        intolerance_conditions = tuple(_parse_conditions(self.answers.get("intolerances", "")))
        all_conditions = tuple(dict.fromkeys(conditions + intolerance_conditions))

        return UserProfile(
            age=int(_number(self.answers["age"])),
            sex=_parse_sex(self.answers["sex"]),
            height_cm=_number(self.answers["height_cm"]),
            weight_kg=_number(self.answers["weight_kg"]),
            goal=_parse_goal(self.answers["goal"]),
            activity=_parse_activity(self.answers["activity"]),
            meal_count=int(_number(self.answers["meal_count"])),
            cooking_time=_parse_cooking_time(self.answers["cooking_time"]),
            restrictions=tuple(restrictions),
            conditions=all_conditions,
            allow_lactose_free_dairy=True,
            allow_gluten_free_oats=False,
        )


def start_session() -> QuestionnaireSession:
    return QuestionnaireSession()


def _normalize_answer(key: str, answer: str) -> str:
    if not answer.strip():
        raise ValueError("Ответ не должен быть пустым.")

    if key == "conditions":
        normalized = normalize_conditions(answer)
        if normalized.errors:
            raise ValueError(normalized.errors[0])
        return ", ".join(normalized.items)

    if key in {"allergies", "intolerances", "excluded_foods"}:
        normalized = normalize_free_text_list(answer)
        if normalized.errors:
            raise ValueError(normalized.errors[0])
        return ", ".join(normalized.items)

    _validate_answer(key, answer)
    return answer.strip()


def _validate_answer(key: str, answer: str) -> None:
    if not answer.strip():
        raise ValueError("Ответ не должен быть пустым.")
    if key in {"age", "height_cm", "weight_kg", "meal_count"}:
        value = _number(answer)
        if key in {"age", "meal_count"} and not value.is_integer():
            raise ValueError("Введите целое число.")
        if key == "age" and not 1 <= value <= 120:
            raise ValueError("Возраст должен быть числом от 1 до 120.")
        if key == "height_cm" and not 90 <= value <= 240:
            raise ValueError("Рост должен быть в сантиметрах, например 178.")
        if key == "weight_kg" and not 25 <= value <= 300:
            raise ValueError("Вес должен быть в килограммах, например 86.")
        if key == "meal_count" and int(value) not in {3, 4, 5}:
            raise ValueError("Для MVP выберите 3, 4 или 5 приемов пищи.")
    elif key == "sex":
        _parse_sex(answer)
    elif key == "goal":
        _parse_goal(answer)
    elif key == "activity":
        _parse_activity(answer)
    elif key == "cooking_time":
        _parse_cooking_time(answer)


def _number(value: str) -> float:
    normalized = normalize_text(value).replace(",", ".")
    try:
        return float(normalized)
    except ValueError as error:
        raise ValueError("Введите число.") from error


def _parse_sex(value: str) -> Sex:
    normalized = normalize_text(value)
    if normalized in {"м", "male"} or "муж" in normalized:
        return Sex.MALE
    if normalized in {"ж", "female"} or "жен" in normalized:
        return Sex.FEMALE
    raise ValueError("Напишите 'мужчина' или 'женщина'.")


def _parse_goal(value: str) -> Goal:
    normalized = normalize_text(value)
    if any(word in normalized for word in ("похуд", "снижен", "дефицит", "lose")):
        return Goal.LOSE
    if any(word in normalized for word in ("поддерж", "норм", "maintain")):
        return Goal.MAINTAIN
    if any(word in normalized for word in ("набор", "масса", "gain")):
        return Goal.GAIN
    raise ValueError("Напишите цель: похудение, поддержание или набор.")


def _parse_activity(value: str) -> ActivityLevel:
    normalized = normalize_text(value)
    if normalized in {"1", "sedentary"} or "сидяч" in normalized or "низк" in normalized or "малоподвиж" in normalized:
        return ActivityLevel.SEDENTARY
    if normalized in {"2", "light"} or "легк" in normalized:
        return ActivityLevel.LIGHT
    if normalized in {"3", "moderate"} or "умерен" in normalized or "средн" in normalized:
        return ActivityLevel.MODERATE
    if normalized in {"4", "active"} or ("высок" in normalized and "очень" not in normalized) or "активная" in normalized:
        return ActivityLevel.ACTIVE
    if normalized in {"5", "very active", "very_active"} or "очень высок" in normalized or "очень актив" in normalized:
        return ActivityLevel.VERY_ACTIVE
    raise ValueError("Выберите активность: сидячая, легкая, умеренная, высокая или очень высокая.")


def _parse_cooking_time(value: str) -> CookingTimePreference:
    normalized = normalize_text(value).replace("–", "-").replace("—", "-")
    if normalized in {"1", "quick"} or "до 15" in normalized or "до15" in normalized:
        return CookingTimePreference.QUICK
    if normalized in {"2", "medium"} or "15-30" in normalized or "15 - 30" in normalized:
        return CookingTimePreference.MEDIUM
    if normalized in {"3", "long"} or "более 30" in normalized or "больше 30" in normalized:
        return CookingTimePreference.LONG
    raise ValueError("Выберите время готовки: до 15 минут, 15–30 минут или более 30 минут.")


def _split_list(value: str) -> list[str]:
    return normalize_stored_free_text_items(value)


def _intolerance_restrictions(value: str) -> list[Restriction]:
    return [Restriction(RestrictionType.INTOLERANCE, item) for item in _split_list(value)]


def _parse_conditions(value: str) -> list[ConditionCode]:
    return normalize_stored_condition_codes(value)
