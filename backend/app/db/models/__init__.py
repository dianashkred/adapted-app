"""All ORM models; importing this package registers every table on Base.metadata."""

from app.db.models.reference import AdaptationRule, PrivacyNotice
from app.db.models.identity import Account, Learner
from app.db.models.course import Chunk, Course, Document, Section
from app.db.models.assessment import Attempt, Question, QuestionOption, Quiz, QuizItem
from app.db.models.learning import AdaptationEvent, ReviewItem, TopicState
from app.db.models.chat import ChatSession, Message, MessageSource
from app.db.models.experiment import SimulatedGap, TestForm, TestFormItem

__all__ = [
    "AdaptationRule", "PrivacyNotice", "Account", "Learner", "Course", "Document", "Section", "Chunk",
    "Question", "QuestionOption", "Quiz", "QuizItem", "Attempt", "TopicState", "AdaptationEvent", "ReviewItem",
    "ChatSession", "Message", "MessageSource", "TestForm", "TestFormItem", "SimulatedGap",
]

# Groups used by the documentation and the colour-coded schema diagram.
TABLE_GROUPS = {
    "Reference data": ["privacy_notice", "adaptation_rule"],
    "Identity": ["account", "learner"],
    "Course materials": ["course", "document", "section", "chunk"],
    "Assessment": ["question", "question_option", "quiz", "quiz_item", "attempt"],
    "Learner model": ["topic_state", "adaptation_event", "review_item"],
    "Chat": ["chat_session", "message", "message_source"],
    "Experiment": ["test_form", "test_form_item", "simulated_gap"],
}
