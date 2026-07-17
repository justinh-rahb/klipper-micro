#!/usr/bin/env sh
set -eu

cmake -S tests/native -B build/native-tests
cmake --build build/native-tests
ctest --test-dir build/native-tests --output-on-failure
