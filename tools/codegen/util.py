def _unsupported(what, node=None):
    span = getattr(node, "span", None)
    loc = f"{span.line}:{span.col}" if span else "?"
    from tools.codegen import CodegenError
    raise CodegenError(f"{loc}: codegen no soporta {what} (MVP int/float/list/struct subset)")