# Test plan

Pytest covers application health/rendering, scheduling allocation and overlap prevention, lifecycle transition validation, timestamp-ordered timelines, and append-only event recording. Validation reports include SQLite foreign-key integrity and report missing timeline tables separately from invalid timeline order. MySQL integration and high-volume concurrency tests require a configured MySQL service and are not asserted by the SQLite unit suite.
