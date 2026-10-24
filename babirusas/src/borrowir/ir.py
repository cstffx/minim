"""Babirusas IR (BIR) - estructuras de datos compartidas."""
from dataclasses import dataclass, field
from typing import List, Optional, Any


@dataclass
class Type:
    kind: str
    name: Optional[str] = None
    elem: Optional["Type"] = None
    fields: List[tuple] = field(default_factory=list)
    length: Optional[int] = None
    ref_kind: Optional[str] = None
    pointee: Optional["Type"] = None


@dataclass
class Place:
    kind: str
    name: Optional[str] = None
    base: Optional["Place"] = None
    field: Optional[str] = None
    idx: Optional["Rvalue"] = None

    def path(self):
        if self.kind == "local":
            return ("local", self.name)
        if self.kind == "field":
            return self.base.path() + ("field", self.field)
        if self.kind == "index":
            return self.base.path() + ("index",)
        if self.kind == "deref":
            return self.base.path() + ("deref",)
        return (self.kind,)


@dataclass(init=False)
class Rvalue:
    kind: str
    place: Optional[Place] = None
    const_type: Optional[Type] = None
    const_value: Any = None
    op: Optional[str] = None
    a: Optional["Rvalue"] = None
    b: Optional["Rvalue"] = None
    ref_kind: Optional[str] = None
    ref_place: Optional[Place] = None
    cast_type: Optional[Type] = None
    agg_kind: Optional[str] = None
    items: List["Rvalue"] = field(default_factory=list)
    idx: Optional["Rvalue"] = None

    def __init__(self, kind, place=None, const_type=None, const_value=None,
                 op=None, a=None, b=None, ref_kind=None, ref_place=None,
                 cast_type=None, agg_kind=None, items=None, idx=None,
                 agg_fields=None):
        # `items` es el nombre canonico del BIR. Se acepta `agg_fields` como
        # alias de la IR historica de `tools/bir.py` para que ninguna de las
        # dos formas de construir un agregado lance TypeError.
        self.kind = kind
        self.place = place
        self.const_type = const_type
        self.const_value = const_value
        self.op = op
        self.a = a
        self.b = b
        self.ref_kind = ref_kind
        self.ref_place = ref_place
        self.cast_type = cast_type
        self.agg_kind = agg_kind
        if items is None:
            items = agg_fields if agg_fields is not None else []
        self.items = list(items)
        self.idx = idx

    @property
    def agg_fields(self):
        return self.items

    @agg_fields.setter
    def agg_fields(self, value):
        self.items = list(value or [])

    def used_places(self):
        res = []
        if self.kind == "use" and self.place is not None:
            res.append(self.place)
        if self.kind == "ref" and self.ref_place is not None:
            res.append(self.ref_place)
        if self.kind == "index" and self.idx is not None:
            res += self.idx.used_places()
        if self.a is not None:
            res += self.a.used_places()
        if self.b is not None:
            res += self.b.used_places()
        for it in self.items:
            res += it.used_places()
        return res


@dataclass
class Stmt:
    kind: str
    place: Optional[Place] = None
    rvalue: Optional[Rvalue] = None
    borrow_kind: Optional[str] = None
    borrow_target: Optional[str] = None
    call_func: Optional[str] = None
    call_args: List[Rvalue] = field(default_factory=list)
    call_dest: Optional[Place] = None
    call_target: Optional[int] = None
    span: Optional[Any] = None
    init: bool = False


@dataclass
class Term:
    kind: str
    target: Optional[int] = None
    discr: Optional[Rvalue] = None
    cases: List[tuple] = field(default_factory=list)
    otherwise: Optional[int] = None
    span: Optional[Any] = None


@dataclass
class Block:
    id: int
    stmts: List[Stmt] = field(default_factory=list)
    terminator: Optional[Term] = None


@dataclass
class Param:
    name: str
    type: Type
    mutable: bool = False
    mode: Optional[str] = None   # "shared" (por defecto), "unique" o "move"
    span: Optional[Any] = None


@dataclass
class Local:
    name: str
    type: Type
    mutable: bool = False
    span: Optional[Any] = None
    # Locales de referencia que mantiene viva una closure capturada.
    captures: List[str] = field(default_factory=list)


@dataclass
class Function:
    name: str
    params: List[Param] = field(default_factory=list)
    locals: List[Local] = field(default_factory=list)
    blocks: List[Block] = field(default_factory=list)
    entry: int = 0
    # Tipo de retorno y local donde el traductor deja el valor de `Return`.
    # Opcionales para no romper funciones BIR construidas a mano.
    ret_type: Optional[Type] = None
    ret_local: Optional[str] = None


def place_str(p: Place) -> str:
    if p.kind == "local":
        return p.name or "?"
    if p.kind == "field":
        return f"{place_str(p.base)}.{p.field}"
    if p.kind == "index":
        return f"{place_str(p.base)}[...]"
    if p.kind == "deref":
        return f"*{place_str(p.base)}"
    return "?"
