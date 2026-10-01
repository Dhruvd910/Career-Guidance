from app.core.db import Base
from app.models.career import CareerAssessment, CareerOption
from app.models.chat import Conversation, Message
from app.models.college import Branch, College, CollegeCourse, Course
from app.models.cutoff import Cutoff
from app.models.exam import Exam, ExamProfile
from app.models.facility import Facility
from app.models.fee import Fee
from app.models.hostel import Hostel
from app.models.memory import (
    Consent, CounsellingThread, DataRequest, MemoryItem, SessionSummary, StudentConstraint, StudentEvent,
    StudentGoal, StudentInterest, TurnAnalysis,
)
from app.models.mock_test import MockTest
from app.models.nearby import NearbyPlace
from app.models.placement import Placement
from app.models.practice import AttemptAnswer, Question, QuestionExam, TestAttempt
from app.models.review import CollegeReview
from app.models.saved_item import SavedItem
from app.models.student import AcademicRecord, StudentProfile
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "StudentProfile",
    "AcademicRecord",
    "Exam",
    "ExamProfile",
    "MockTest",
    "Question",
    "QuestionExam",
    "TestAttempt",
    "AttemptAnswer",
    "CareerOption",
    "CareerAssessment",
    "College",
    "Course",
    "Branch",
    "CollegeCourse",
    "Cutoff",
    "Fee",
    "Hostel",
    "Facility",
    "Placement",
    "NearbyPlace",
    "CollegeReview",
    "Conversation",
    "Message",
    "SavedItem",
    "Consent",
    "DataRequest",
    "StudentInterest",
    "StudentGoal",
    "StudentConstraint",
    "CounsellingThread",
    "SessionSummary",
    "StudentEvent",
    "MemoryItem",
    "TurnAnalysis",
]
