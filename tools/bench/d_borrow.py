def push_all(dst, src):
    for x in src:
        dst.append(x)


def first_or(v, d):
    if not v:
        return d
    return v[0]
