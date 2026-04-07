"""Domain service interface exports.

Design:
	This package exposes abstract service contracts used by the domain and
	application layers to depend on capabilities instead of concrete providers.

Maintenance:
	Keep only interfaces and domain-facing protocols here. Adapter selection
	and implementation wiring belong in infrastructure and composition roots.
"""
