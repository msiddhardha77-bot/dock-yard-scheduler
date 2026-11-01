import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from app import db
from app.models.events import AnomalyLabel, GroundTruthRecord
from validation.validate import validation_summary


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _write_model(model, output_dir):
    columns = [column.name for column in model.__table__.columns]
    path = output_dir / f"{model.__tablename__}.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for item in model.query.order_by(model.id):
            writer.writerow({name: json.dumps(_json_value(getattr(item, name))) if isinstance(getattr(item, name), (dict, list)) else _json_value(getattr(item, name)) for name in columns})
    return path


def export_database(output_dir="output/export", seed=None, mode=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    db.create_all()
    models = sorted(db.Model.registry.mappers, key=lambda mapper: mapper.class_.__tablename__)
    files = []
    counts = {}
    for mapper in models:
        model = mapper.class_
        path = _write_model(model, output_dir)
        files.append(path.name)
        counts[model.__tablename__] = model.query.count()
    manifest = {"generator_version": "1.0", "seed": seed, "mode": mode, "synthetic": True,
                "generation_timestamp": datetime.utcnow().isoformat() + "Z", "counts": counts,
                "files": files, "checksum_scope": "canonical CSV bytes excluding this manifest"}
    checksums = {}
    for filename in files:
        checksums[filename] = hashlib.sha256((output_dir / filename).read_bytes()).hexdigest()
    manifest["checksums"] = checksums
    (output_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "ground_truth.json").write_text(json.dumps([
        {"appointment_id": row.appointment_id, "label": row.label, "source": row.source}
        for row in AnomalyLabel.query.order_by(AnomalyLabel.id)
    ], indent=2), encoding="utf-8")
    (output_dir / "validation_summary.json").write_text(json.dumps(validation_summary(db.session), indent=2, default=str), encoding="utf-8")
    (output_dir / "README.md").write_text("# Generated Dock Yard Dataset\n\nSynthetic exports generated from the configured database. See `source_manifest.json` for counts and checksums.\n", encoding="utf-8")
    return manifest
