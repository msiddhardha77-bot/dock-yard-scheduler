# DockFlow checksum discrepancy investigation

Date: 2026-11-01 (Asia/Calcutta)

Scope: read-only workspace and SQLite inspection. No database, manifest,
historical report, schema, or application workflow was modified or executed.

## Checksums under investigation

| Description | SHA-256 |
|---|---|
| Original accepted checksum | `2979787d6f9ec722a44f69773d4bd7b340e905e1db1e6567ebc13f11e9c0caea` |
| Current baseline | `aedad28dc9a2877a53b7458946ef56002ed46df7cc5714643163a0c4b9969526` |
| Current working copy | `aedad28dc9a2877a53b7458946ef56002ed46df7cc5714643163a0c4b9969526` |

## 1. Candidate file search

The workspace was recursively scanned for SQLite/database extensions and
database-related backup/archive/temp names, excluding the virtual environment
and Python caches. The following database files were found:

| Candidate path | Bytes | SHA-256 | SQLite facts |
|---|---:|---|---|
| `D:\dock-yard-scheduler\dockyard.db` | 303,104 | `755941ef522b2605c06d0bd7832a0fed4aa115b41b73a8b02e9a6bbe0e43e564` | 160 appointments; 0 lifecycle events |
| `D:\dock-yard-scheduler\full_dataset.db` | 34,816,000 | `acf36dce8cd0e3789778a03ff4bd14a85dc5665d51ecabe9a29f971d2818a258` | 20,000 appointments; 100,000 lifecycle events |
| `D:\dock-yard-scheduler\full_dataset_corrected.db` | 34,816,000 | `aedad28dc9a2877a53b7458946ef56002ed46df7cc5714643163a0c4b9969526` | 20,000 appointments; 100,005 lifecycle events |
| `D:\dock-yard-scheduler\full_dataset_corrected.local.db` | 34,816,000 | `aedad28dc9a2877a53b7458946ef56002ed46df7cc5714643163a0c4b9969526` | Exact byte/hash copy of current baseline |

No `.bak`, `.backup`, `.dump`, `.sqlite`, `.sqlite3`, `.db-wal`, `.db-shm`,
`.zip`, `.7z`, `.tar`, or `.gz` database/archive candidates were found outside
the excluded virtual-environment package files. No file exactly matches the
original accepted checksum. The original database has not been recovered.

## 2. Current database counts

The following were executed against `full_dataset_corrected.db` using a
read-only SQLite connection:

```sql
SELECT status, COUNT(*)
FROM appointments
GROUP BY status
ORDER BY status;
```

```text
DEPARTED    1
REJECTED   52
SCHEDULED  19947
```

```sql
SELECT COUNT(*) FROM appointments;
SELECT COUNT(*) FROM lifecycle_events;
SELECT COUNT(*) FROM operational_exceptions;
SELECT status, COUNT(*) FROM operational_exceptions GROUP BY status;
```

```text
appointments             20000
lifecycle_events         100005
operational_exceptions   1
operational exception    RESOLVED 1
```

Other changed table counts relative to the historical manifest are:

```text
check_in_events       manifest 1       current 2
gate_visits           manifest 0       current 1
labor_assignments     manifest 19948   current 19947
yard_occupancy        manifest 0       current 1
```

## 3. Historical manifest/report comparison

The historical manifest and validation report both record:

```text
appointments       20000
lifecycle_events   100000
SCHEDULED          19948
REJECTED           52
operational errors 0
```

The current database therefore retains all 20,000 appointment rows but does
not retain the original lifecycle/event and operational state exactly. It has
five additional lifecycle events and one additional exception workflow. The
working copy is an exact copy of this current state, not an independently
recovered accepted state.

## 4. File timestamps and available logs

Relevant filesystem timestamps:

| File | Created | Last modified |
|---|---|---|
| `full_dataset_corrected.db` | 2026-11-01 09:42:26 | 2026-11-01 14:57:27 |
| `full_dataset_corrected_manifest.json` | 2026-11-01 09:49:29 | 2026-11-01 09:49:29 |
| `full_dataset_corrected_validation_summary.json` | 2026-11-01 09:49:29 | 2026-11-01 09:49:29 |
| `full_dataset_corrected.local.db` | 2026-11-01 15:15:20 | copied from baseline |

The database modification time is after the manifest and validation report
were written. The database contains a later operational timestamp sequence:

```text
2026-11-01 09:27:07.194981  GATE_CHECK_IN
2026-11-01 09:27:10.562472  DOCK_ASSIGNMENT
2026-11-01 09:27:12.812795  SERVICE_START
2026-11-01 09:27:15.041014  SERVICE_COMPLETE
2026-11-01 09:27:16.118221  GATE_CHECK_OUT
2026-11-01 09:27:27.615550  exception resolution timestamp
```

The available `logs/` files contain generation/reset supervision output and no
Flask check-in, checkout, exception-detection, or exception-resolution audit
log. Consequently, the exact operating-system process or user action cannot
be proven from available logs. The row changes are consistent with the normal
check-in/service/checkout and exception-resolution routes, but that is a
correlation, not proof of the initiating process.

## 5. Change signature

The current-only rows and updates form one coherent workflow for appointment
ID 1:

- status changed from `SCHEDULED` to `DEPARTED`;
- five lifecycle events were appended, IDs `100001` through `100005`;
- one accepted check-in event was added;
- one gate visit was added;
- one yard-occupancy row was added;
- the appointment's labor assignment was removed;
- its dock and yard reservations were closed/completed;
- one `LATE_ARRIVAL` exception was created and resolved.

The original scheduling decision remains accepted. This is an operational
workflow mutation after generation, not evidence that the scheduler generated
a different accepted population. The exact initiating command/request is not
present in the workspace logs.

## Findings

1. No workspace copy matches the original accepted SHA-256.
2. `full_dataset.db` matches the historical high-level counts but has a third,
   different checksum and is not an accepted-checksum recovery.
3. `full_dataset_corrected.db` has 20,000 appointments but 100,005 lifecycle
   events and one operational exception.
4. The current baseline and working copy are identical; the working copy does
   not introduce a second discrepancy.
5. Available timestamps place the current database write after the historical
   manifest/report generation, while the database's operational rows identify
   the likely workflow shape but not the exact actor/process.

No restoration claim is made. Recovering the accepted database would require an
external artifact whose complete SHA-256 equals
`2979787d6f9ec722a44f69773d4bd7b340e905e1db1e6567ebc13f11e9c0caea`.
