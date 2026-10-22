"""BIR — in-memory intermediate representation (CFG-based).

Mirrors babirusas/IR.md. This is the data model the borrow checker and
codegen consume. BBIR (binary) is just a serialization of these structures.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Union


# ---------- Types ----------

class TypeKind(IntEnum):
    UNIT = 0; BOOL = 1
    I8 = 2; I16 = 3; I32 = 4; I64 = 5
    U8 = 6; U16 = 7; U32 = 8; U64 = 9
    F32 = 10; F64 = 11
    STR = 12
    STRUCT = 0x10; ARRAY = 0x11; SLICE = 0x12; REF = 0x13


@dataclass
class Type:
    kind: TypeKind
    # payload
    name: str = ""                 # struct name
    fields: List[tuple] = field(default_factory=list)  # [(name, Type)]
    elem: Optional["Type"] = None  # array/slice/ref pointee
    length: int = 0                # array length
    ref_kind: int = 0              # 0=shared,1=mut (for REF)


# ---------- Places ----------

class PlaceKind(IntEnum):
    LOCAL = 0; FIELD = 1; INDEX = 2; DEREF = 3


@dataclass
class Place:
    kind: PlaceKind
    name: str = ""                 # LOCAL
    base: Optional["Place"] = None # FIELD/INDEX/DEREF
    field: str = ""                # FIELD
    idx: Optional["Rvalue"] = None  # INDEX


# ---------- Rvalues ----------

class RvalueKind(IntEnum):
    USE = 0; CONST = 1; BINOP = 2; UNARYOP = 3
    REF = 4; CAST = 5; AGGREGATE = 6


@dataclass
class Rvalue:
    kind: RvalueKind
    place: Optional[Place] = None
    const_type: Optional[Type] = None
    const_value: object = None
    op: int = 0
    a: Optional["Rvalue"] = None
    b: Optional["Rvalue"] = None
    ref_kind: int = 0              # for REF
    cast_type: Optional[Type] = None
    agg_kind: int = 0
    agg_fields: List["Rvalue"] = field(default_factory=list)


# ---------- Statements ----------

class StmtKind(IntEnum):
    STORAGE_LIVE = 0; STORAGE_DEAD = 1; ASSIGN = 2
    BORROW = 3; CALL = 4; DROP = 5; NOP = 6


@dataclass
class Stmt:
    kind: StmtKind
    place: Optional[Place] = None   # for STORAGE_*/ASSIGN/DROP
    rvalue: Optional[Rvalue] = None # for ASSIGN
    borrow_kind: int = 0            # for BORROW (0=shared,1=mut)
    borrow_place: Optional[Place] = None
    borrow_target: str = ""         # local name
    func: str = ""                 # for CALL
    args: List[Rvalue] = field(default_factory=list)
    dest: Optional[Place] = None
    target: int = 0                # block id after call


# ---------- Terminators ----------

class TermKind(IntEnum):
    GOTO = 0; SWITCHINT = 1; RETURN = 2; UNREACHABLE = 3


@dataclass
class Term:
    kind: TermKind
    target: int = 0                # GOTO
    discr: Optional[Rvalue] = None # SWITCHINT
    cases: List[tuple] = field(default_factory=list)  # [(value, blockid)]
    otherwise: int = 0


# ---------- Blocks / Function ----------

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


@dataclass
class Local:
    name: str
    type: Type
    mutable: bool = False


@dataclass
class Function:
    name: str
    params: List[Param] = field(default_factory=list)
    locals: List[Local] = field(default_factory=list)
    blocks: List[Block] = field(default_factory=list)
    entry: int = 0


@dataclass
class Module:
    functions: List[Function] = field(default_factory=list)
