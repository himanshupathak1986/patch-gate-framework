# PATCH-GATE Reviewer Experiment Environment

Date: 2026-11-08
OS: macOS 26.5 (25F71)
Architecture: arm64
Processor: Apple M5
Memory: 16 GB
Python: 3.14.6
Original commit: 98c67b68844c3d72936e9b3f5717418cf2122d4d

## Scanner versions
Name: ruff
Version: 0.17.2
Name: bandit
Version: 1.9.4
Name: radon
Version: 6.0.1

## Validation
Existing pytest suite: 29 passed
Constructed diagnostic scenarios: 13
Public patch records: 60

## Limitations
- Alternative policy runtimes were not measured.
- No independent vulnerability ground truth was collected.
- Machine load was not characterized.
- Constructed diagnostic cases are separate from public patches.
