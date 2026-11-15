import enum

from sqlalchemy import Enum as SAEnum


def pg_enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(py_enum, name=name, values_callable=lambda e: [m.value for m in e], create_type=True)


class AccountRole(str, enum.Enum):
    STUDENT = "student"
    ADMIN = "admin"


class ExperimentMode(str, enum.Enum):
    PLAIN_RAG = "plain_rag"
    ADAPTIVE = "adaptive"


class DifficultyLevel(str, enum.Enum):
    BASIC = "basic"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class CourseVisibility(str, enum.Enum):
    PRIVATE = "private"
    SHARED = "shared"


class DocumentStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class QuestionKind(str, enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    FREE_TEXT = "free_text"


class QuestionSource(str, enum.Enum):
    GENERATED = "generated"
    CURATED = "curated"


class QuizKind(str, enum.Enum):
    CHECK = "check"
    REVIEW = "review"
    PRE_TEST = "pre_test"
    POST_TEST = "post_test"
    TOPIC_QUIZ = "topic_quiz"
    REVISION = "revision"


class QuizStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class TopicStatus(str, enum.Enum):
    NOT_CHECKED = "not_checked"
    GAP = "gap"
    MASTERED = "mastered"


class CheckEndReason(str, enum.Enum):
    SUCCESS_SEQUENCE = "success_sequence"
    TWO_CONSECUTIVE_ERRORS = "two_consecutive_errors"
    QUESTION_LIMIT = "question_limit"
    STOPPED_BY_LEARNER = "stopped_by_learner"


class EvaluationMethod(str, enum.Enum):
    AUTO = "auto"
    LLM = "llm"


class ChatMode(str, enum.Enum):
    GUIDED = "guided"
    FREE_QUESTION = "free_question"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class TestKind(str, enum.Enum):
    __test__ = False
    PRE_TEST = "pre_test"
    POST_TEST = "post_test"


class AnswerConfidence(str, enum.Enum):
    SURE = "sure"
    NOT_SURE = "not_sure"
    GUESSING = "guessing"


class ReviewReason(str, enum.Enum):
    INCORRECT = "incorrect"
    UNSURE = "unsure"


class UiTheme(str, enum.Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"
