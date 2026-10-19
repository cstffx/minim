"""AST nodes for Minim."""

from dataclasses import dataclass, field
from typing import List, Optional, Union, Tuple


@dataclass
class Span:
    line: int
    col: int
    end_line: int = 0
    end_col: int = 0


# ---- Top level ----
@dataclass
class Program:
    stmts: List["Stmt"]
    span: Optional["Span"] = None


# ---- Statements ----
@dataclass
class UseDecl:
    paths: List[List[str]]  # list of path (list of names)
    span: Optional["Span"] = None


@dataclass
class LetDecl:
    name: str
    type_: Optional["Type"]
    value: "Expr"
    span: Optional["Span"] = None


@dataclass
class VarDecl:
    bindings: List["Binding"]
    value: "Expr"
    span: Optional["Span"] = None


@dataclass
class FnDecl:
    name: str
    tparams: List["TParam"]
    params: List["Param"]
    ret: Optional["Type"]
    body: "Suite"
    span: Optional["Span"] = None


@dataclass
class TypeDecl:
    name: str
    tparams: List["TParam"]
    members: List["Member"]
    span: Optional["Span"] = None


@dataclass
class TraitDecl:
    name: str
    methods: List["FnSig"]
    span: Optional["Span"] = None


@dataclass
class Field:
    name: str
    type_: Optional["Type"]
    default: Optional["Expr"]
    span: Optional["Span"] = None


@dataclass
class Variant:
    name: str
    fields: List["FieldName"]
    members: List["Member"]
    span: Optional["Span"] = None


@dataclass
class FieldName:
    name: str
    type_: Optional["Type"]
    span: Optional["Span"] = None


@dataclass
class FnSig:
    name: str
    params: List["Param"]
    ret: Optional["Type"]
    span: Optional["Span"] = None


@dataclass
class Member:
    kind: str  # 'field', 'variant', 'fn', 'let', 'var'
    node: object
    span: Optional["Span"] = None


@dataclass
class LetStmt:
    bindings: List["Binding"]
    value: "Expr"
    span: Optional["Span"] = None


@dataclass
class VarStmt:
    bindings: List["Binding"]
    value: "Expr"
    span: Optional["Span"] = None


@dataclass
class Assign:
    place: "Place"
    op: str
    value: "Expr"
    span: Optional["Span"] = None


@dataclass
class Place:
    name: str
    parts: List  # list of ('field', name) or ('index', expr)
    span: Optional["Span"] = None


@dataclass
class ExprStmt:
    expr: "Expr"
    span: Optional["Span"] = None


@dataclass
class IfStmt:
    cond: "Expr"
    then: "Suite"
    elifs: List  # list of (cond, suite)
    else_: Optional["Suite"]
    span: Optional["Span"] = None


@dataclass
class WhileStmt:
    cond: "Expr"
    body: "Suite"
    span: Optional["Span"] = None


@dataclass
class ForStmt:
    bindings: List["Binding"]
    iter: "Expr"
    body: "Suite"
    span: Optional["Span"] = None


@dataclass
class MatchStmt:
    expr: "Expr"
    arms: List["Arm"]
    span: Optional["Span"] = None


@dataclass
class Arm:
    pattern: "Pattern"
    guard: Optional["Expr"]
    body: Union["Expr", "Suite"]  # if Expr, it's armBody = expr
    is_else: bool = False
    span: Optional["Span"] = None


@dataclass
class ReturnStmt:
    value: Optional["Expr"]
    span: Optional["Span"] = None


@dataclass
class SpawnStmt:
    expr: "Expr"
    span: Optional["Span"] = None


@dataclass
class AwaitStmt:
    expr: "Expr"
    span: Optional["Span"] = None


@dataclass
class BreakStmt:
    pass
    span: Optional["Span"] = None


@dataclass
class ContinueStmt:
    pass
    span: Optional["Span"] = None


@dataclass
class Suite:
    stmts: List["Stmt"]
    span: Optional["Span"] = None


@dataclass
class OrBlock:
    body: "Suite"
    span: Optional["Span"] = None


# ---- Bindings / Patterns ----
@dataclass
class Binding:
    kind: str  # 'name', 'variant', 'tuple'
    name: Optional[str] = None
    type_: Optional["Type"] = None
    variant: Optional[str] = None
    patterns: Optional[List["Pattern"]] = None
    tuple_patterns: Optional[List["Pattern"]] = None
    span: Optional["Span"] = None


@dataclass
class Pattern:
    kind: str  # 'literal', 'name', 'variant', 'named_field', 'tuple'
    value: object = None  # literal value or name
    name: Optional[str] = None
    patterns: Optional[List["Pattern"]] = None
    field_name: Optional[str] = None
    sub: Optional["Pattern"] = None
    span: Optional["Span"] = None


# ---- Expressions ----
@dataclass
class Expr:
    node: object
    span: Optional["Span"] = None


@dataclass
class OrExpr:
    left: "Expr"
    rights: List  # list of ('or', expr) or ('or', OrBlock)
    span: Optional["Span"] = None


@dataclass
class BinOp:
    op: str
    left: "Expr"
    right: "Expr"
    span: Optional["Span"] = None


@dataclass
class UnaryOp:
    op: str
    operand: "Expr"
    span: Optional["Span"] = None


@dataclass
class Postfix:
    base: "Expr"
    ops: List  # list of tuples
    span: Optional["Span"] = None


@dataclass
class Call:
    args: List["Arg"]
    span: Optional["Span"] = None


@dataclass
class Arg:
    label: Optional["Expr"]  # None if positional, expr if named (expr: expr)
    value: "Expr"
    is_named: bool = False
    span: Optional["Span"] = None


@dataclass
class Lambda:
    params: List["Param"]
    body: "Expr"
    span: Optional["Span"] = None


@dataclass
class IfExpr:
    cond: "Expr"
    then: "Expr"
    else_: "Expr"
    span: Optional["Span"] = None


@dataclass
class MatchExpr:
    expr: "Expr"
    arms: List["Arm"]
    one_line: bool = False
    span: Optional["Span"] = None


@dataclass
class BlockExpr:
    node: object
    span: Optional["Span"] = None


# ---- Primary expressions (wrapped) ----
@dataclass
class IntLit:
    value: str
    span: Optional["Span"] = None


@dataclass
class FloatLit:
    value: str
    span: Optional["Span"] = None


@dataclass
class StrLit:
    value: str
    span: Optional["Span"] = None


@dataclass
class FStrLit:
    value: str
    span: Optional["Span"] = None


@dataclass
class RStrLit:
    value: str
    span: Optional["Span"] = None


@dataclass
class BytesLit:
    value: str
    span: Optional["Span"] = None


@dataclass
class MlStrLit:
    value: str
    span: Optional["Span"] = None


@dataclass
class BoolLit:
    value: bool
    span: Optional["Span"] = None


@dataclass
class NilLit:
    pass
    span: Optional["Span"] = None


@dataclass
class NameExpr:
    name: str
    span: Optional["Span"] = None


@dataclass
class SelfExpr:
    pass
    span: Optional["Span"] = None


@dataclass
class ItExpr:
    pass
    span: Optional["Span"] = None


@dataclass
class BorrowExpr:
    operand: "Expr"
    span: Optional["Span"] = None


@dataclass
class TupleExpr:
    items: List["Expr"]
    span: Optional["Span"] = None


@dataclass
class ListExpr:
    items: List["Arg"]
    span: Optional["Span"] = None


@dataclass
class MapExpr:
    items: List["Arg"]
    span: Optional["Span"] = None


@dataclass
class MoveExpr:
    lambda_: "Lambda"
    span: Optional["Span"] = None


# ---- Types ----
@dataclass
class Type:
    node: object


@dataclass
class TypeName:
    name: str
    args: List["Type"]


@dataclass
class TypeList:
    inner: "Type"


@dataclass
class TypeMap:
    key: "Type"
    val: "Type"


@dataclass
class TypeSet:
    inner: "Type"


@dataclass
class TypeBorrow:
    inner: "Type"


@dataclass
class TypeTuple:
    items: List["Type"]


@dataclass
class TypeFunc:
    params: List["Type"]
    ret: "Type"


@dataclass
class TypeParen:
    inner: "Type"


@dataclass
class TypeSuffix:
    base: "Type"
    suffix: str  # '!' or '?'


@dataclass
class TParam:
    name: str
    bound: Optional["Type"]


@dataclass
class Param:
    mode: Optional[str]  # 'var', 'move', or None
    name: str
    type_: Optional["Type"]
    default: Optional["Expr"]


# ---- Stmt union type alias (not enforced) ----
Stmt = Union[UseDecl, LetDecl, VarDecl, FnDecl, TypeDecl, TraitDecl, LetStmt, VarStmt,
             Assign, IfStmt, WhileStmt, ForStmt, MatchStmt, ReturnStmt, SpawnStmt,
             AwaitStmt, BreakStmt, ContinueStmt, ExprStmt]