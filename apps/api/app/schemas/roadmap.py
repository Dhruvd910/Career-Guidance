from pydantic import BaseModel


class RoadmapStep(BaseModel):
    order: int
    title: str
    description: str
    status: str  # done | current | upcoming


class RoadmapResponse(BaseModel):
    steps: list[RoadmapStep]
    current_milestone: str
    next_action: str
    long_term_goal: str
    # Chapter-by-chapter plan for the student's target exam (None while they're exploring):
    # {"exam", "exam_name", "phases": [...], "subjects": [{"name", "tips", "resources", "extra",
    #   "classes": [{"class_level", "focus", "chapters": [{"name", "weight", "where"}]}]}], "sources"}
    study_plan: dict | None = None
