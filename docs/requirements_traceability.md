# Requirements traceability

| ID | Business requirement | Existing implementation | Status | Work performed | Evidence |
|---|---|---|---|---|---|
| R-01 | Normalized facility, dock, shipment, appointment, carrier, vehicle, labor, exception, and event records | `app/models/*.py` | verified | Existing models reviewed; additive `YardSlot`, `HandlingRequirement`, and `CheckInEvent` models added | `pytest -v`, model tests |
| R-02 | Stable identifiers and relationship integrity | Model unique keys and foreign keys | partial | Existing reference conventions preserved; new check-in IDs use `CHECK-<appointment>-NN` | model definitions; no migration against user DB |
| R-03 | Operating hours, windows, dock, labor, yard, and overlap scheduling | `app/services/scheduler.py` | verified | Central reason-code explanations and handling restrictions added | scheduler tests |
| R-04 | Refrigerated and hazardous compatibility | `HandlingRequirement`, dock type checks | verified | Full generator creates 2,000 refrigerated and 1,000 hazardous requirements with dedicated dock types; scheduler rejects incompatible docks | full isolated count/integrity query and focused test |
| R-05 | Lifecycle, gate, checkout, exceptions, append-only history | `lifecycle.py`, `checkins.py`, `events.py` | verified | Early check-in attempts are recorded and rejected; no-show and resolution covered | lifecycle/web tests |
| R-06 | Starter/full deterministic generation | `generator/generate.py` | verified | Full counts, event links, integrity, and fixed-seed hashes previously verified | `docs/progress.md` verification record |
| R-07 | Required labelled negative scenarios | `validation/scenario_evaluator.py` | verified | All five scenarios execute against isolated SQLite using real scheduling/check-in services and produce JSON outcomes | evaluator run: 5/5 passed |
| R-08 | CSV/JSON exports and source manifest | `generator/export.py` | verified | Database export writes entity CSVs, ground truth JSON, manifest checksums, validation summary, and dataset README | isolated full export |
| R-09 | Database-backed evaluation metrics | `metrics.py`, `docs/metrics.md` | partial | Timeline-derived wait, dock, and yard durations now calculate from source timestamps; labor utilization remains unavailable without productive labor intervals | `timeline_metrics()` full-run output |
| R-10 | Integrity and reproducibility validation | `validation/*.py` | verified | Full isolated runs have linked counts, canonical CSV hashes, and matching same-seed exports | full-final2 export hashes |
| R-11 | Responsive web workflows and reports | routes/templates/tests | verified | Creation, detail, filter, reschedule, cancel, gate, exception, report routes return and mutate through backend workflows | 13-test suite and live HTTP checks |
| R-12 | MySQL integration and concurrency proof | `DATABASE_URL`/SQLAlchemy configuration | blocked | No MySQL service or credentials available | explicitly unverified |
