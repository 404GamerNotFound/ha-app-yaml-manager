#!/usr/bin/env python3
"""Provide one-shot Git HTTPS credentials without putting tokens in URLs."""

import os
import sys


prompt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
value = os.environ.get("YAML_MANAGER_GIT_USERNAME", "") if "username" in prompt else os.environ.get("YAML_MANAGER_GIT_TOKEN", "")
print(value)
