#!/bin/bash
# Re-run on every container start (Trinity convention): survives base-image updates.
# cryptography signs the Google service account token (no Google client library needed).
pip install --user --quiet "cryptography>=42"
