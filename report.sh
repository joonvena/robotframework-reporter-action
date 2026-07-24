#!/bin/bash
set -e

REPORT_PATH=$(pwd)/$REPORT_PATH

REPORT_PATH="$REPORT_PATH" python3 "$(dirname "$0")/reporter.py"
