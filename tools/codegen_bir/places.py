from tools.wasm_encoder import *
from babirusas.src.borrowir.ir import Type
from .layouts import LayoutError, wasm_repr


def _i32_load(offset):
    """i32.load with alignment=2 (4 bytes)"""
    return bytes([0x28]) + uleb128(2) + uleb128(offset)


def _i64_load(offset):
    """i64.load with alignment=3 (8 bytes)"""
    return bytes([0x29]) + uleb128(3) + uleb128(offset)


def _f64_load(offset):
    """f64.load with alignment=3 (8 bytes)"""
    return bytes([0x2B]) + uleb128(3) + uleb128(offset)


def _i32_add():
    """i32.add"""
    return bytes([0x6A])


def _i64_add():
    """i64.add"""
    return bytes([0x7C])


def _i64_mul():
    """i64.mul"""
    return bytes([0x7E])


class BIRPlacesMixin:
    def _place_type(self, place):
        """Determine the BIR type of a place (recursively)."""
        if place.kind == "local":
            return self._local_type(place.name)
        elif place.kind == "field":
            # Get base type, then look up field type
            base_ty = self._place_type(place.base)
            if base_ty is None:
                return None
            if base_ty.kind == "struct":
                if base_ty.name in getattr(self.layouts, "sum_types", set()):
                    for vname in (self.layouts.variant_index.get(base_ty.name) or {}):
                        for fname, wtype, off, fty in self.variant_fields(base_ty.name, vname):
                            if fname == place.field:
                                return fty
                    return None
                return self.field_type(base_ty.name, place.field)
            elif base_ty.kind == "tuple":
                fields, _ = self.tuple_layout(base_ty)
                for fname, wtype, off, fty in fields:
                    if fname == place.field:
                        return fty
                return None
            elif base_ty.kind == "list":
                if place.field == "len" or place.field == "cap":
                    return Type("i64")
                if place.field == "data":
                    return base_ty
                return None
            else:
                return None
        elif place.kind == "index":
            # Get base type, then extract element type
            base_ty = self._place_type(place.base)
            if base_ty is None:
                return None
            if base_ty.kind == "list" and base_ty.elem is not None:
                return base_ty.elem
            return None
        self._fail(f"place '{place.kind}' no soportado en 6.2.3")

    def _gen_place_get(self, place):
        """Generate WASM code to read from a place (recursively).

        Handles:
        - local: local_get
        - field: base_ptr + field_offset, then load
        - index: base_ptr + (idx * size), then load
        """
        if place.kind == "local":
            return local_get(self._local_idx(place.name))

        elif place.kind == "field":
            base_ty = self._place_type(place.base)
            field_ty = self._place_type(place)

            if base_ty is None or field_ty is None:
                self._fail(f"tipo desconocido para campo '{place.field}'")

            if base_ty.kind == "struct":
                base_code = self._gen_place_get(place.base)
                if base_ty.name in getattr(self.layouts, "sum_types", set()):
                    offset = None
                    for vname in (self.layouts.variant_index.get(base_ty.name) or {}):
                        for fname, wtype, off, fty in self.variant_fields(base_ty.name, vname):
                            if fname == place.field:
                                offset = off
                                break
                        if offset is not None:
                            break
                    if offset is None:
                        self._fail(f"campo '{place.field}' no existe en suma '{base_ty.name}'")
                    return base_code + self._load_field(field_ty, offset)
                offset = self.field_offset(base_ty.name, place.field)
                return base_code + self._load_field(field_ty, offset)

            elif base_ty.kind == "tuple":
                # Look up field in tuple layout
                fields, _ = self.tuple_layout(base_ty)
                for fname, wtype, off, fty in fields:
                    if fname == place.field:
                        base_code = self._gen_place_get(place.base)
                        return base_code + self._load_field(field_ty, off)
                self._fail(f"campo '{place.field}' no existe en tupla")

            elif base_ty.kind == "list":
                base_code = self._gen_place_get(place.base)
                if place.field == "len" or place.field == "cap":
                    return base_code + _i32_load(0 if place.field == "len" else 4) + bytes([0xAC])
                if place.field == "data":
                    return base_code + _i32_load(8)
                self._fail(f"campo '{place.field}' no existe en lista")

            else:
                self._fail(f"acceso a campo en tipo '{base_ty.kind}' no soportado")

        elif place.kind == "index":
            # Array indexing: base_ptr + (idx * element_size)
            base_ty = self._place_type(place.base)
            elem_ty = self._place_type(place)

            if base_ty is None or base_ty.kind != "list" or elem_ty is None:
                self._fail(f"indexacion en tipo '{base_ty.kind if base_ty else 'unknown'}' no soportada")

            # Los slots de lista ocupan 8 bytes.
            base_code = self._gen_place_get(place.base)
            # data ptr esta en header+8
            data_code = base_code + _i32_load(8)

            # Get index value (coercion a i64)
            idx_code = self._gen_rvalue(place.idx) + self._coerce(self._rv_type(place.idx), WasmEncoder.I64)

            # Compute offset: idx * 8
            offset_code = idx_code + i64_const(8) + _i64_mul()

            # Add data_ptr + offset
            result = data_code + offset_code + bytes([0xA7])  # i32.wrap_i64
            result += _i32_add()

            # Load from computed address
            return result + self._load_field(elem_ty, 0)

        self._fail(f"place '{place.kind}' no soportado en 6.2.3")

    def _gen_place_set(self, place, value_code, value_ty=None):
        """Generate WASM code to write to a place (recursively).

        Handles local, field, index, nested. value_code leaves the value on
        the stack; this method arranges address + value + store.
        """
        if place.kind == "local":
            return value_code + local_set(self._local_idx(place.name))

        elif place.kind == "field":
            base_ty = self._place_type(place.base)
            field_ty = self._place_type(place)

            if base_ty is None or field_ty is None:
                self._fail(f"tipo desconocido para campo '{place.field}'")

            if base_ty.kind == "struct":
                wtype = wasm_repr(field_ty)
                if value_ty is not None:
                    value_code = value_code + self._coerce(value_ty, wtype)
                base_code = self._gen_place_get(place.base)
                if base_ty.name in getattr(self.layouts, "sum_types", set()):
                    offset = None
                    for vname in (self.layouts.variant_index.get(base_ty.name) or {}):
                        for fname, wt, off, fty in self.variant_fields(base_ty.name, vname):
                            if fname == place.field:
                                offset = off
                                break
                        if offset is not None:
                            break
                    if offset is None:
                        self._fail(f"campo '{place.field}' no existe en suma '{base_ty.name}'")
                    return base_code + value_code + self._store_wtype(wtype, offset)
                offset = self.field_offset(base_ty.name, place.field)
                return base_code + value_code + self._store_field(field_ty, offset)

            elif base_ty.kind == "tuple":
                fields, _ = self.tuple_layout(base_ty)
                for fname, wtype, off, fty in fields:
                    if fname == place.field:
                        if value_ty is not None:
                            value_code = value_code + self._coerce(value_ty, wtype)
                        base_code = self._gen_place_get(place.base)
                        return base_code + value_code + self._store_wtype(wtype, off)
                self._fail(f"campo '{place.field}' no existe en tupla")

            else:
                self._fail(f"acceso a campo en tipo '{base_ty.kind}' no soportado")

        elif place.kind == "index":
            base_ty = self._place_type(place.base)
            elem_ty = self._place_type(place)

            if base_ty is None or base_ty.kind != "list" or elem_ty is None:
                self._fail(f"indexacion en tipo '{base_ty.kind if base_ty else 'unknown'}' no soportada")

            # Direccion del slot (8 bytes) en el array de datos.
            base_code = self._gen_place_get(place.base)
            data_code = base_code + _i32_load(8)
            idx_code = self._gen_rvalue(place.idx) + self._coerce(self._rv_type(place.idx), WasmEncoder.I64)
            offset_code = idx_code + i64_const(8) + _i64_mul()
            addr_code = data_code + offset_code + bytes([0xA7])  # i32.wrap_i64
            addr_code += _i32_add()

            # Coercion al slot de 8 bytes.
            if value_ty is not None:
                if elem_ty.kind == "f64":
                    value_code = value_code + self._coerce(value_ty, WasmEncoder.F64)
                else:
                    value_code = value_code + self._coerce_slot(value_ty)
            else:
                # Asumir que value_code ya tiene el tipo correcto del slot.
                pass

            if elem_ty.kind == "f64":
                return addr_code + value_code + (bytes([0x39]) + uleb128(3) + uleb128(0))
            else:
                return addr_code + value_code + (bytes([0x37]) + uleb128(3) + uleb128(0))

        self._fail(f"place '{place.kind}' no soportado en 6.2.4")

    def _store_field(self, ty, offset):
        try:
            wtype = wasm_repr(ty)
        except LayoutError:
            wtype = WasmEncoder.I64
        if wtype == WasmEncoder.F64:
            return bytes([0x39]) + uleb128(3) + uleb128(offset)
        if wtype == WasmEncoder.I32:
            return bytes([0x36]) + uleb128(2) + uleb128(offset)
        return bytes([0x37]) + uleb128(3) + uleb128(offset)

    @staticmethod
    def _store_wtype(wtype, offset):
        if wtype == WasmEncoder.F64:
            return bytes([0x39]) + uleb128(3) + uleb128(offset)
        if wtype == WasmEncoder.I32:
            return bytes([0x36]) + uleb128(2) + uleb128(offset)
        return bytes([0x37]) + uleb128(3) + uleb128(offset)

    def _load_field(self, ty, offset):
        """Generate load instruction for a type at given offset."""
        if ty is None:
            self._fail("tipo desconocido en carga")

        kind = ty.kind
        if kind == "f64":
            return _f64_load(offset)
        elif kind in ("i64", "bool"):
            return _i64_load(offset)
        elif kind == "i32":
            return _i32_load(offset)
        elif kind in ("str", "bytes", "struct", "tuple", "list", "map", "set",
                      "func", "closure", "ref"):
            # Pointers are i32
            return _i32_load(offset)
        else:
            self._fail(f"carga de tipo '{kind}' no soportada")
