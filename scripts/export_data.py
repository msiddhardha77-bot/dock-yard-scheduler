import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from generator.export import export_database

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output/export")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--mode")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        print(export_database(args.output, args.seed, args.mode))
