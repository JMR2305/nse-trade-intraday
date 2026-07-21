"""Stub for execution/exceptions.py - RC-7 frozen module."""

class ExecutionException(Exception):
    pass

class InvalidStateTransition(ExecutionException):
    pass

class OrderValidationError(ExecutionException):
    pass

class IdempotencyViolation(ExecutionException):
    pass

class OverfillError(ExecutionException):
    pass

class ConcurrentTransitionError(ExecutionException):
    pass
