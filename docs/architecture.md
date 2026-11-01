# Architecture

The Flask application factory configures SQLAlchemy and Flask-Migrate. Routes handle HTTP concerns; services own scheduling, capacity, compatibility, lifecycle, exception, and metric logic. Models are split into master data, operations, scheduling, and event/audit tables.

