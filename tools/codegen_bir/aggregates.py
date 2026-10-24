"""Agregados y memoria lineal para el backend BIR (fase 6.2.2).

El BIR representa tuplas, productos y sumas como punteros a memoria lineal.
Este mixin implementa el allocator bump-pointer compartido con el backend AST
(`_ctor_begin`/`_ctor_end`) y la construccion de `Rvalue("aggregate")` para
`tuple`, `list`, `struct` y `variant`.

La memoria se reparte desde el global `heap` (inicializado en 4096, igual que
el backend AST) y los objetos se construyen de forma recursiva: cada constructor
salva la base exterior en la pila wasm, reserva su region y restaura la base al
terminar. Asi dos instancias del mismo agregado nunca comparten memoria.
"""
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from babirusas.src.borrowir.ir import Type

from .layouts import LayoutError, wasm_repr


# Store/load helpers. Cada slot sigue la alineacion natural que usa el backend
# AST: i32/f32 a 4 bytes, i64/f64 a 8 bytes.
_I32_STORE = bytes([0x36])
_I64_STORE = bytes([0x37])
_F64_STORE = bytes([0x39])
_I32_ADD = bytes([0x6A])
_I32_WRAP_I64 = bytes([0xA7])
_I64_EXTEND_I32_U = bytes([0xAC])
_I64_EXTEND_I32_S = bytes([0xAD])
_I64_TRUNC_F64_S = bytes([0xB0])
_F64_CONVERT_I64_S = bytes([0xB9])


class BIRAggregatesMixin:
    # ---- allocator bump-pointer compartido ----

    def _ensure_allocator(self):
        """Crea (la primera vez) los globales del heap y del constructor."""
        if getattr(self, "_allocator_ready", False):
            return
        self.heap_global = self.enc.add_global(WasmEncoder.I32, True,
                                               i32_const(4096))
        self.tmp_global = self.enc.add_global(WasmEncoder.I32, True,
                                              i32_const(0))
        self.ctor_base_global = self.enc.add_global(WasmEncoder.I32, True,
                                                    i32_const(0))
        self._allocator_ready = True

    def _ctor_begin(self, size):
        """Reserva `size` bytes y deja en la pila la base exterior anterior."""
        self._ensure_allocator()
        return (GLOBAL_GET(self.ctor_base_global) +   # base exterior (queda en pila)
                GLOBAL_GET(self.heap_global) +        # nueva base
                GLOBAL_SET(self.ctor_base_global) +
                GLOBAL_GET(self.heap_global) +
                i32_const(size) +
                _I32_ADD +
                GLOBAL_SET(self.heap_global))

    def _ctor_end(self):
        """Devuelve la base nueva y restaura la base exterior."""
        self._ensure_allocator()
        return (GLOBAL_GET(self.ctor_base_global) +
                GLOBAL_SET(self.tmp_global) +
                GLOBAL_SET(self.ctor_base_global) +
                GLOBAL_GET(self.tmp_global))

    def _zero_value(self, ty):
        """Codigo que deja en la pila el cero del tipo BIR `ty`."""
        try:
            wt = wasm_repr(ty)
        except LayoutError:
            wt = WasmEncoder.I64
        if wt == WasmEncoder.F64:
            return f64_const(0.0)
        if wt == WasmEncoder.I32:
            return i32_const(0)
        return i64_const(0)

    # ---- tipos / dispatch ----

    def _rv_type(self, rv):
        if rv.kind == "aggregate":
            return self._aggregate_type(rv)
        return super()._rv_type(rv)

    def _aggregate_type(self, rv):
        kind = rv.agg_kind
        if kind == "tuple":
            return Type("tuple", fields=[
                (str(i), self._rv_type(it) or Type("i64"))
                for i, it in enumerate(rv.items or [])])
        if kind in ("struct", "variant"):
            name = str(rv.const_value or "").split(".", 1)[0]
            return Type("struct", name=name)
        if kind == "list":
            elem = self._rv_type(rv.items[0]) if rv.items else Type("unknown")
            return Type("list", elem=elem)
        return Type("unknown")

    def _gen_rvalue(self, rv):
        if rv.kind == "aggregate":
            return self._gen_aggregate(rv)
        return super()._gen_rvalue(rv)

    def _gen_aggregate(self, rv):
        kind = rv.agg_kind
        if kind == "tuple":
            return self._gen_tuple_aggregate(rv)
        if kind == "struct":
            return self._gen_product_aggregate(rv)
        if kind == "variant":
            return self._gen_variant_aggregate(rv)
        if kind == "list":
            return self._gen_list_aggregate(rv)
        self._fail(f"agregado '{kind}' no soportado todavia "
                   f"(map/set/closure llegan en 6.3)")

    # ---- tuplas ----

    def _gen_tuple_aggregate(self, rv):
        ty = self._aggregate_type(rv)
        fields, size = self.tuple_layout(ty)
        code = bytearray(self._ctor_begin(size))
        for i, (name, wtype, offset, fty) in enumerate(fields):
            code += GLOBAL_GET(self.ctor_base_global)
            if i < len(rv.items or []):
                item = rv.items[i]
                code += self._gen_rvalue(item)
                code += self._coerce(self._rv_type(item), wtype)
            else:
                code += self._zero_value(fty)
            code += self._store_slot(wtype, offset)
        code += self._ctor_end()
        return bytes(code)

    # ---- productos (struct) ----

    def _gen_product_aggregate(self, rv):
        type_name = str(rv.const_value or "")
        raw_fields = self.layouts.fields(type_name)
        if not raw_fields and not self.layouts.has_type(type_name):
            self._fail(f"tipo '{type_name}' sin layout registrado")
        size = self.layouts.size(type_name)
        items = rv.items or []
        code = bytearray(self._ctor_begin(size))
        for i, (fname, wtype, offset, ftc, _default) in enumerate(raw_fields):
            code += GLOBAL_GET(self.ctor_base_global)
            if i < len(items):
                item = items[i]
                code += self._gen_rvalue(item)
                code += self._coerce(self._rv_type(item), wtype)
            else:
                code += self._zero_wtype(wtype)
            code += self._store_slot(wtype, offset)
        code += self._ctor_end()
        return bytes(code)

    # ---- sumas (variant) ----

    def _gen_variant_aggregate(self, rv):
        full = str(rv.const_value or "")
        type_name, _, variant_name = full.partition(".")
        if not type_name or not variant_name:
            self._fail(f"variante sin tipo: '{full}'")
        tag = self.layouts.variant_index.get(type_name, {}).get(variant_name)
        if tag is None:
            self._fail(f"variante '{full}' sin layout registrado")
        raw_fields = self.layouts.variant_fields_of(type_name, variant_name)
        size = self.layouts.size(type_name)
        items = rv.items or []
        code = bytearray(self._ctor_begin(size))
        # tag en el offset 0
        code += GLOBAL_GET(self.ctor_base_global)
        code += i32_const(tag)
        code += _I32_STORE + _uleb128_static(2) + _uleb128_static(0)
        for i, (fname, wtype, offset, ftc, _default) in enumerate(raw_fields):
            code += GLOBAL_GET(self.ctor_base_global)
            if i < len(items):
                item = items[i]
                code += self._gen_rvalue(item)
                code += self._coerce(self._rv_type(item), wtype)
            else:
                code += self._zero_wtype(wtype)
            code += self._store_slot(wtype, offset)
        code += self._ctor_end()
        return bytes(code)

    # ---- listas ----

    def _gen_list_aggregate(self, rv):
        """Header de 16 bytes (len, cap, data) + slots de 8 bytes."""
        items = rv.items or []
        n = len(items)
        cap = n if n > 4 else 4
        size = 16 + cap * 8
        code = bytearray(self._ctor_begin(size))
        # len
        code += GLOBAL_GET(self.ctor_base_global)
        code += i32_const(n)
        code += _I32_STORE + _uleb128_static(2) + _uleb128_static(0)
        # cap
        code += GLOBAL_GET(self.ctor_base_global)
        code += i32_const(cap)
        code += _I32_STORE + _uleb128_static(2) + _uleb128_static(4)
        # data = base + 16
        code += GLOBAL_GET(self.ctor_base_global)
        code += GLOBAL_GET(self.ctor_base_global)
        code += i32_const(16)
        code += _I32_ADD
        code += _I32_STORE + _uleb128_static(2) + _uleb128_static(8)
        for i, item in enumerate(items):
            elem_ty = self._rv_type(item)
            wt = self._slot_wtype(elem_ty)
            code += GLOBAL_GET(self.ctor_base_global)
            code += i32_const(16 + i * 8)
            code += _I32_ADD
            code += self._gen_rvalue(item)
            if wt == WasmEncoder.F64:
                code += _F64_STORE + _uleb128_static(3) + _uleb128_static(0)
            else:
                code += self._coerce_slot(elem_ty)
                code += _I64_STORE + _uleb128_static(3) + _uleb128_static(0)
        code += self._ctor_end()
        return bytes(code)

    # ---- stores y coerciones ----

    @staticmethod
    def _slot_wtype(ty):
        """Tipo wasm del slot de 8 bytes de una lista."""
        try:
            return wasm_repr(ty)
        except LayoutError:
            return WasmEncoder.I64

    @staticmethod
    def _store_slot(wtype, offset):
        if wtype == WasmEncoder.F64:
            return _F64_STORE + _uleb128_static(3) + _uleb128_static(offset)
        if wtype == WasmEncoder.I32:
            return _I32_STORE + _uleb128_static(2) + _uleb128_static(offset)
        return _I64_STORE + _uleb128_static(3) + _uleb128_static(offset)

    def _zero_wtype(self, wtype):
        if wtype == WasmEncoder.F64:
            return f64_const(0.0)
        if wtype == WasmEncoder.I32:
            return i32_const(0)
        return i64_const(0)

    @staticmethod
    def _coerce(src_ty, wtype):
        """Ajusta el valor de la pila al tipo wasm del slot de destino."""
        src = src_ty.kind if src_ty is not None else "unknown"
        if wtype == WasmEncoder.F64:
            if src == "f64":
                return b""
            if src == "i32":
                return _I64_EXTEND_I32_S + _F64_CONVERT_I64_S
            return _F64_CONVERT_I64_S
        if wtype == WasmEncoder.I64:
            if src == "f64":
                return _I64_TRUNC_F64_S
            if src == "i32":
                return _I64_EXTEND_I32_U
            return b""
        # i32
        if src == "f64":
            return _I64_TRUNC_F64_S + _I32_WRAP_I64
        if src in ("i64", "bool", "unit", "unknown", "err"):
            return _I32_WRAP_I64
        return b""

    @staticmethod
    def _coerce_slot(src_ty):
        """Los slots de lista son de 8 bytes: punteros/bools -> i64."""
        src = src_ty.kind if src_ty is not None else "unknown"
        if src == "f64":
            return b""
        if src == "i32" or src in ("str", "bytes", "struct", "tuple", "list",
                                   "map", "set", "func", "closure", "ref"):
            return _I64_EXTEND_I32_U
        return b""
