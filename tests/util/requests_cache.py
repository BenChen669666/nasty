#
# Copyright 2019 Lukas Schmelzeisen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import pickle
from logging import getLogger
from multiprocessing import Lock
from pathlib import Path
from typing import Any, Callable, Dict, TypeVar, cast
from unittest.mock import patch

from requests import PreparedRequest, Response, Session
from typing_extensions import Final

logger = getLogger(__name__)

_T_func = TypeVar("_T_func", bound=Callable[..., Any])

_LOCK: Final = Lock()
_ORIG_SESSION_SEND: Final[Callable[..., Response]] = Session.send
_CACHE_FILE: Final = Path(__file__).parent / ".requests_cache.pickle"


class _CacheKey:
    def __init__(self, request: PreparedRequest):
        if any(request.hooks.values()):
            raise NotImplementedError("Usage of hooks not supported.")

        self._method: Final = request.method
        self._url: Final = request.url
        self._headers: Final = frozenset(request.headers.items())
        self._cookies: Final = frozenset(request._cookies.items())  # type: ignore
        self._body: Final = request.body
        self._body_position: Final = request._body_position  # type: ignore

    def __hash__(self) -> int:
        return hash(frozenset(self.__dict__.items()))

    def __eq__(self, other: object) -> bool:
        return type(self) == type(other) and self.__dict__ == other.__dict__


def requests_cache(regenerate: bool = False) -> Callable[[_T_func], _T_func]:
    def _mock_requests_send(
        self: Session, request: PreparedRequest, **kwargs: Any
    ) -> Response:
        key = _CacheKey(request)

        with _LOCK:
            cache: Dict[_CacheKey, Response] = {}
            if _CACHE_FILE.exists():
                with _CACHE_FILE.open("rb") as fin:
                    cache = pickle.load(fin)

            response = cache.get(key)
            if response is not None:
                logger.debug(
                    "Found cache response"
                    + ("." if not regenerate else " (regenerating).")
                )

                if not regenerate:
                    self.cookies.update(response.cookies)  # type: ignore
                    return response

                cache.pop(key)

            response = _ORIG_SESSION_SEND(self, request, **kwargs)
            cache[key] = response

            with _CACHE_FILE.open("wb") as fout:
                pickle.dump(cache, fout, pickle.HIGHEST_PROTOCOL)

            return response

    def decorator(func: _T_func) -> _T_func:
        @patch.object(Session, "send", _mock_requests_send)
        def patched_func(*args, **kwargs):  # type: ignore
            return func(*args, **kwargs)

        return cast(_T_func, patched_func)

    return decorator