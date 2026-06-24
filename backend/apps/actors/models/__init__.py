"""Actors layer: the Actor table and the ActorModel base its satellites inherit."""

from .actor import Actor, ActorResolutionStatus
from .base import ActorModel

__all__ = [
    "Actor",
    "ActorModel",
    "ActorResolutionStatus",
]
