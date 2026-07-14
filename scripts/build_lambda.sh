#!/usr/bin/env bash
# Build dist/lambda.zip for the arm64 python3.12 Lambda runtime.
# Deps are installed inside an arm64 linux container so compiled wheels
# (pydantic-core) match the Lambda architecture regardless of the host.
set -euo pipefail
cd "$(dirname "$0")/.."

BUILD_DIR=dist/lambda_build
rm -rf dist && mkdir -p "$BUILD_DIR"

docker run --rm --platform linux/arm64 \
  -v "$PWD":/src -w /src python:3.12-slim \
  pip install --quiet --target "/src/$BUILD_DIR" \
  feedparser==6.0.11 requests==2.32.4 pydantic==2.11.7 \
  pydantic-settings==2.10.1 tenacity==9.1.2

cp -R shared "$BUILD_DIR/shared"
mkdir -p "$BUILD_DIR/services/producer"
cp services/__init__.py "$BUILD_DIR/services/__init__.py"
cp services/producer/__init__.py services/producer/fetch.py services/producer/publish.py \
   "$BUILD_DIR/services/producer/"
cp services/ingest_lambda/handler.py "$BUILD_DIR/handler.py"

(cd "$BUILD_DIR" && zip -qr ../lambda.zip .)
echo "built dist/lambda.zip ($(du -h dist/lambda.zip | cut -f1))"
