class DomainError(Exception):
    code = "DOMAIN_ERROR"

class TaskNotFoundError(DomainError):
    code = "TASK_NOT_FOUND"
    def __init__(self, task_id):
        super().__init__(f"Task {task_id} not found")

class ProjectNotFoundError(DomainError):
    code = "PROJECT_NOT_FOUND"
    def __init__(self, project_id):
        super().__init__(f"Project {project_id} not found")

class UserNotFoundError(DomainError):
    code = "USER_NOT_FOUND"
    def __init__(self, user_id):
        super().__init__(f"User {user_id} not found")

class PermissionDeniedError(DomainError):
    code = "PERMISSION_DENIED"

class VersionConflictError(DomainError):
    code = "VERSION_CONFLICT"
    def __init__(self):
        super().__init__("Task was modified by another request — refetch and retry")

class UnauthenticatedError(DomainError):
    code = "UNAUTHENTICATED"
    def __init__(self):
        super().__init__("X-User-Id header is required for this operation")