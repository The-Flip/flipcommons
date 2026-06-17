# Documentation

This directory contains the stable product, architecture, development, and operations documentation for Flipcommons.

For setup and common commands, start with the repository [README](../README.md). For historical design notes and implementation plans, use [plans/README.md](plans/README.md).

## Start Here

- [Overview.md](Overview.md) what Flipcommons is, who it serves, and why the product is shaped the way it is.
- [Architecture.md](Architecture.md) top-level system map.
- [DomainModel.md](DomainModel.md) the pinball catalog domain model.

## Product And Domain

- [Personas.md](Personas.md) the main user groups the product serves.
- [Definitions.md](Definitions.md) defines pinball terminology used by the product and data model.
- [DomainModel.md](DomainModel.md) pinball catalog concepts like titles, models, variants, series
- [SingleModelTitles.md](SingleModelTitles.md) how the product handles titles with exactly one model.
- [RecordLifecycle.md](RecordLifecycle.md) creation, deletion, restore, and duplicate-prevention semantics.
- [Privacy.md](Privacy.md) privacy principles and analytics expectations.
- [SmallTeam.md](SmallTeam.md) operating principles for a small team.

## Architecture

- [Architecture.md](Architecture.md) overall Django + SvelteKit system, request topology, same-origin model, API layer, and SSR/CSR split.
- [AppBoundaries.md](AppBoundaries.md) Django app responsibilities and dependency rules.
- [ApiDesign.md](ApiDesign.md) endpoint design and schema design heuristics.
- [Authz.md](Authz.md) authorization activities, policy gates, and capability surfaces.
- [Provenance.md](Provenance.md) claims, resolution, audit history, provenance invariants.
- [Citations.md](Citations.md) backing up claims with evidence.
- [Media.md](Media.md) media storage, uploads, claims, attachment resolution.
- [Hosting.md](Hosting.md) Railway deployment topology.
- [Observability.md](Observability.md) Error monitoring and alerting.
- [Analytics.md](Analytics.md) Analytics setup and privacy posture.
- [DeployAutomation.md](DeployAutomation.md) philosophy behind the deploy safeguards.
  - [BuildChecks.md](BuildChecks.md) build-phase refusal gate (Dockerfile, sourcemap upload, build-time secrets).
  - [DeployChecks.md](DeployChecks.md) pre-deploy refusal gate (Django system checks).

## Backend Development

- [Python.md](Python.md) backend typing and Python style decisions.
- [DataModeling.md](DataModeling.md) database modeling principles and constraint patterns.
- [EntityNaming.md](EntityNaming.md) entity naming rules and where canonical names live.
- [TestingBackend.md](TestingBackend.md) backend test strategy and constraint testing.

## Frontend Development

- [Typescript.md](Typescript.md) frontend TypeScript conventions.
- [Svelte.md](Svelte.md) Svelte 5 authoring conventions and rendering strategy.
- [DetailLayoutPatterns.md](DetailLayoutPatterns.md) detail-page layout patterns.
- [TestingFrontend.md](TestingFrontend.md) frontend test tiers and DOM test patterns.

## Working With Data

- [Data.md](Data.md) index for working with catalog data: where it comes from, how to correct it via YAML patches, where to explore via DuckDB.
  - [DataPatches.md](DataPatches.md) numbered, replayable data patches — the sole bulk write path for catalog data.
    - [DataPatchAuthoring.md](DataPatchAuthoring.md) authoring guidance: hand-authored vs generated, descriptions, vocab sequencing, validation.
      - [DataPatchKit.md](DataPatchKit.md) the `patchkit` generator workflow for large curated patch sets.
    - [DataPatchReviewing.md](DataPatchReviewing.md) how to editorially review a data patch.

## Testing And Review

- [Testing.md](Testing.md) overall testing strategy.
- [Reviewing.md](Reviewing.md) repo-specific review priorities and checks.

## Agent Docs

- [AGENTS.src.md](AGENTS.src.md) is the source for generated AI-agent guidance. Do not edit generated `AGENTS.md` or `CLAUDE.md` directly.

## Historical Plans

- [plans/README.md](plans/README.md) how to use historical planning documents. Plan docs are useful for context and rationale, but they are not canonical current documentation.
