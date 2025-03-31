from typing import NotRequired, TypedDict


class APSWExecuteKwargs(TypedDict):
    can_cache: NotRequired[bool]
    prepare_flags: NotRequired[int]
    explain: NotRequired[int]
