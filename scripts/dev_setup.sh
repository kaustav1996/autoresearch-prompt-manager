#!/bin/bash
# Install all packages in dev mode
set -e

cd "$(dirname "$0")/.."

echo "Installing packages in dev mode..."
pip install -e "packages/shonku[dev]"
pip install -e "packages/prompt_manager[dev,api,client,metric]"
pip install -e "packages/autoresearcher_shonku[dev]"
pip install -e "packages/example[dev]"

echo ""
echo "Running all tests..."
python3 -m pytest packages/shonku/tests -q
python3 -m pytest packages/prompt_manager/tests -q
python3 -m pytest packages/autoresearcher_shonku/tests -q
python3 -m pytest packages/example/tests -q

echo ""
echo "All packages installed and tests passing."
