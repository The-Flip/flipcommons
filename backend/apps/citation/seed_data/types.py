"""Shared types for citation seed data literals."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class SeedLink(TypedDict):
    url: str
    link_type: str
    label: NotRequired[str]


class SeedSource(TypedDict):
    name: str
    source_type: str
    author: NotRequired[str]
    publisher: NotRequired[str]
    year: NotRequired[int]
    month: NotRequired[int]
    day: NotRequired[int]
    date_note: NotRequired[str]
    isbn: NotRequired[str]
    description: NotRequired[str]
    identifier_key: NotRequired[str]
    domains: NotRequired[list[str]]
    links: NotRequired[list[SeedLink]]
    children: NotRequired[list[SeedSource]]
