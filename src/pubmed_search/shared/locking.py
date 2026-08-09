"""Thread-safety helpers for stateful application services."""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Concatenate, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

_InstanceT = TypeVar("_InstanceT")
_Params = ParamSpec("_Params")
_ResultT = TypeVar("_ResultT")


def synchronized(
    method: Callable[Concatenate[_InstanceT, _Params], _ResultT],
) -> Callable[Concatenate[_InstanceT, _Params], _ResultT]:
    """Run an instance method while holding its re-entrant ``_lock``."""

    @wraps(method)
    def wrapper(instance: _InstanceT, /, *args: _Params.args, **kwargs: _Params.kwargs) -> _ResultT:
        lock = getattr(instance, "_lock", None)
        if lock is None:
            msg = f"{type(instance).__name__} must define _lock before calling {method.__name__}"
            raise RuntimeError(msg)
        with lock:
            return method(instance, *args, **kwargs)

    return wrapper


__all__ = ["synchronized"]
