from sqlalchemy import case
from app.models import Task, TaskStatus as ModelStatus, TaskPriority as ModelPriority

PRIORITY_ORDER = {
    ModelPriority.LOW: 0,
    ModelPriority.MEDIUM: 1,
    ModelPriority.HIGH: 2,
    ModelPriority.URGENT: 3,
}

STATUS_ORDER = {
    ModelStatus.TODO: 0,
    ModelStatus.IN_PROGRESS: 1,
    ModelStatus.DONE: 2,
}

PRIORITY_RANK = case(
    {ModelPriority.LOW: 0, ModelPriority.MEDIUM: 1, ModelPriority.HIGH: 2, ModelPriority.URGENT: 3},
    value=Task.priority,
)

STATUS_RANK = case(
    {ModelStatus.TODO: 0, ModelStatus.IN_PROGRESS: 1, ModelStatus.DONE: 2},
    value=Task.status,
)