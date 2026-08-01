# Architecture

## Overview
The Web Intelligence Collector is an isolated service that fetches, parses, deduplicates, and stores public intelligence data. It exposes a read-only REST API.

## Logical Flow
```
Approved Source Registry -> Fetch Scheduler -> Scrapling Fetch Adapter
    -> Raw Snapshot Store -> Source-Specific Parser -> Schema Validation
    -> Deduplication -> Structured Intelligence Store -> Read-Only FastAPI
```

## Isolation Guarantees
- No access to trading engine database
- No Zerodha integration
- No price collection
- No signal generation
- Separate branch: `feature/web-intelligence-collector`

## Components
- **SourceRegistry**: Maintains allow-list of approved sources
- **FetchClient**: Secure HTTP client with rate limiting
- **ScraplingAdapter**: Framework isolation layer
- **SourceParser**: Extensible parser interface
- **SnapshotRepository**: Raw snapshot metadata persistence
- **IntelligenceRepository**: Structured record persistence
- **DeduplicationService**: Deterministic deduplication
- **CollectionService**: Orchestrates the pipeline
- **DataQualityEvaluator**: Quality assessment
