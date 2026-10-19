def push_all(dst: list[int], src: list[int]) -> None:
    for x in src:
        dst.append(x)


def first_or(v: list[int], d: int) -> int:
    if not v:
        return d
    return v[0]
