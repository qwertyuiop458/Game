#!/usr/bin/env python3
"""Backward-compatible CLI wrapper for the modular extractor pipeline.

Core extraction stages live in ``tools/extract_zombie_infection.py`` and the
specialized decoders under ``tools/``.
"""

from tools.extract_zombie_infection import main

if __name__ == '__main__':
    main()
