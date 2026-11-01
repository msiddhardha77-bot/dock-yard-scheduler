# Synthetic dataset generation

The generator uses the same deterministic scheduling and event-generation path
for `starter`, `medium`, and `full` modes. Use a separate database URL for
testing; never point a test run at an operational database.

| Mode | Facilities | Docks | Appointments | Lifecycle events |
|---|---:|---:|---:|---:|
| `starter` | 2 | 20 | 40 | 80 |
| `medium` | 10 | 100 | 1,000 | 2,000 |
| `full` | 10 | 100 | 20,000 | 100,000 |

Pass `--seed 20261022` to reproduce the project target seed. The Python API is
`generate(seed=20261022, mode="starter", database_url=...)`; the CLI accepts
`--mode starter|medium|full`, `--seed`, and an explicit `--database-url`.
`full` is the production-scale dataset mode and must not be used for preflight
testing.

## Generated master data and appointment distribution

Each generated facility has ten docks (six general, two refrigerated, and two
hazardous), ten yard slots with matching handling categories, and day/evening
labor shifts covering 06:00–22:00 with a two-hour 13:00–15:00 shift handover
overlap. The overlap lets appointments finish within one available shift
without requiring a cross-shift appointment to be artificially rejected.
The deliberate `LABOR_UNAVAILABLE` anomaly adds one appointment-specific,
zero-capacity shift and moves only that appointment's assignment to it. It does
not change the staffing capacity of either recurring shift.
Docks support VAN, TRUCK, and TRAILER vehicles. Each run creates 20
deterministic carriers and three deterministic vehicles per carrier:

| Vehicle | Capacity | Relative appointment-selection weight |
|---|---:|---:|
| VAN | 3,500 kg | 3 |
| TRUCK | 12,000 kg | 5 |
| TRAILER | 30,000 kg | 2 |

Vehicle load weights are generated within the selected vehicle's capacity.
Each shipment references the same carrier as its vehicle. Appointment carrier
selection is seeded and spread across the fleet. Facility appointment totals
are allocated deterministically from the configured, modest facility weights
and shuffled with the same seeded random generator. Every facility's
appointments are assigned unique 22-minute start slots over up to 60 days;
the generator fails explicitly if a facility's allocation exceeds the
configured horizon rather than silently reusing dates and times.

Ten percent of generated shipments require refrigeration and five percent
require hazardous handling; these groups are mutually exclusive. Scheduled
baseline appointments must have a compatible dock and yard slot, an active
yard reservation, a dock reservation, and a labor assignment. Deliberate
anomaly records are the only intentional exceptions to normal compatibility
and capacity validation.

## Ground-truth anomaly evidence

Five post-baseline anomalies update both the appointment's `AnomalyLabel` and
its `GroundTruthRecord.truth` fields (`issue_type` and `label`). They use
different appointment records from the baseline allocation:

| Issue type | Evidence stored in ground truth | Data condition tested |
|---|---|---|
| `DOCK_CAPACITY_EXCEEDED` | conflicting appointment ID and dock ID | Exactly one isolated pair of overlapping active reservations share a dock |
| `INCOMPATIBLE_LOAD_ASSIGNMENT` | assigned dock and required refrigerated/hazardous flags | A special-handling shipment is assigned to an otherwise unoccupied general dock |
| `CHECK_IN_BEFORE_APPOINTMENT_DATE` | attempted and scheduled timestamps | A rejected check-in attempt predates its scheduled start |
| `LABOR_UNAVAILABLE` | dedicated shift ID, recurring shift ID, assigned workers, and available workers | One appointment's assigned labor exceeds its dedicated shift capacity; recurring shift staffing remains unchanged |
| `NO_SHOW_NOT_RECORDED` | snapshot and requested-end timestamps | The appointment is overdue at the snapshot with no NO_SHOW lifecycle event |

These are anomaly labels, not `OperationalException` rows. The generator does
not fabricate operational exception records; the returned
`exception_distribution` reports actual exception records separately from
`anomaly_distribution`. The returned `rejection_reason_distribution` gives the
actual scheduler decision reasons for any appointments not allocated
resources; a rejected appointment remains in the dataset with its decision.
The ordinary generated arrivals are ten minutes early, within the arrival
detector's no-exception window. The early check-in is recorded as a rejected
`CheckInEvent`, while the no-show anomaly specifically represents a missing
`NO_SHOW` detection. Neither should create an operational exception. The
deliberate dock, handling, and labor data anomalies are labeled test evidence,
not outcomes emitted by the operational exception detectors. Thus zero
operational exceptions is the correct expected result for these generator
scenarios; actual detected late arrivals, early arrivals beyond the configured
threshold, and no-shows use the normal exception workflow.

## Pre-generation validation

Before a full run, generate starter and medium datasets in disposable SQLite
databases and verify their counts/checksums, foreign-key integrity, parent
relationships, vehicle capacity, resource allocations, lifecycle histories,
timeline ordering, and ground-truth evidence. Confirm that the complete
60-day facility allocation stays within each facility's 2,400 available
appointment start slots. Do not treat SQLite tests as proof of MySQL
transaction or concurrency behavior.

## Seed 20261022 preflight measurements

The starter database was generated twice (40 appointments each) in separate
temporary SQLite files. Both runs had 40 scheduled appointments, 20 carriers,
60 vehicles, 4 refrigerated shipments, and 2 hazardous shipments; their
canonical database checksums matched. Each run took 0.76–0.87 seconds and
occupied 303,104 bytes.

The medium database was also generated twice (1,000 appointments each). Both
runs had matching canonical checksums, 996 scheduled appointments, and four
`DOCK_UNAVAILABLE` rejections. All 10 facilities had appointments; every one
of the 20 carriers served every facility in this seeded sample. The medium
distribution was:

| Measure | Observed |
|---|---:|
| Facility appointments, FAC-001 through FAC-010 | 110, 108, 105, 103, 100, 99, 97, 95, 93, 90 |
| Carrier appointments | 38–66 per carrier |
| VAN / TRUCK / TRAILER shipments | 302 / 506 / 192 |
| Refrigerated / hazardous shipments | 100 / 50 |
| Ground-truth anomaly labels | 995 baseline; one of each of the five issue types |
| Operational exception rows | 0 |
| Medium SQLite file / total rows | 1,671,168 bytes / 12,300 rows |
| Medium runtime | 8.05–9.18 seconds |
| Measured medium peak working set | approximately 83 MiB |

For the 20,000-appointment target, the same deterministic facility allocator
assigns 2,200, 2,160, 2,100, 2,060, 2,000, 1,980, 1,940, 1,900, 1,860, and
1,800 appointments to FAC-001 through FAC-010. The largest allocation fits
within that facility's 2,400 start slots in the 60-day window. Extrapolating
per-table payload from the medium run, including 100,000 lifecycle events and
the observed 99.6% resource-allocation rate, estimates approximately 300,072
database rows and a 38.6 MiB SQLite file. This is a planning estimate; page
growth, indexes, journal/WAL files, and MySQL storage are not measured by it.

The medium runtime implies about 3.1 minutes under simple linear scaling to
20,000 appointments. Allow 3–6 minutes on comparable hardware because query
and event insertion costs can grow with the database. The full-mode lifecycle
event batch is substantially larger than the medium batch, so full-run peak
memory was not measured; budget at least 1 GiB available memory and 1 GiB free
disk for a future controlled full run and its temporary/journal overhead.
No full dataset was generated for these measurements.
