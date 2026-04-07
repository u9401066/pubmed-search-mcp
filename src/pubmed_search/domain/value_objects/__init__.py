"""Domain value object exports.

Design:
	This package gathers immutable domain concepts that carry validation and
	formatting rules but no persistence or transport behavior.

Maintenance:
	Re-export stable value objects here for ergonomic imports. Keep I/O helpers
	and infrastructure concerns outside the domain package.
"""
