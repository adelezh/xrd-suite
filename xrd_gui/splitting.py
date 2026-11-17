"""Strict backend selection: never degrade to another splitting scheme."""
from pyFAI.method_registry import IntegrationMethod


def integration_method(split, dimension=1):
    method = (split, 'csr', 'cython')
    if not IntegrationMethod.select_method(dim=dimension, split=split, algo='csr',
                                          impl='cython', degradable=False):
        raise ValueError(f'pyFAI {dimension}D method {method} is unavailable. '
                         'Install a pyFAI build with this CSR/Cython splitting implementation.')
    return method


def actual_method(result, requested):
    method = result.method
    actual = (method.split.lower(), method.algo.lower(), method.impl.lower())
    if actual != requested:
        raise ValueError(f'pyFAI substituted {actual} for requested {requested}; result discarded.')
    return list(actual)
