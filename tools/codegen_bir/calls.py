from tools.wasm_encoder import *
from babirusas.src.borrowir.ir import Type
from .layouts import LayoutError, wasm_repr


class BIRCallsMixin:
    def _ensure_list_globals(self):
        if getattr(self, "_list_globals_ready", False):
            return
        self.list_val_i64 = self.enc.add_global(WasmEncoder.I64, True, i64_const(0))
        self.list_val_f64 = self.enc.add_global(WasmEncoder.F64, True, f64_const(0.0))
        self.list_tmp_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.list_idx_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.slice_base_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self._list_globals_ready = True

    def _gen_call(self, st):
        name = st.call_func
        args = st.call_args
        # Builtins de colecciones.
        if name.startswith("list."):
            self._ensure_list_globals()
            method = name.split(".", 1)[1]
            if method == "len":
                # args[0] = lista
                code = bytearray()
                code += self._gen_rvalue(args[0])
                code += _i32_load(0)  # len en header offset 0
                code += bytes([0xAC])  # extend i32 -> i64
                if st.call_dest is not None:
                    return self._gen_place_set(st.call_dest, bytes(code), Type("i64"))
                return bytes(code) + DROP if False else bytes(code)
            if method == "get":
                # args: list, idx
                recv_ty = self._rv_type(args[0])
                elem_ty = recv_ty.elem if recv_ty is not None else None
                code = bytearray()
                # idx
                idx_code = self._gen_rvalue(args[1]) + self._coerce(self._rv_type(args[1]), WasmEncoder.I64)
                # base list ptr
                base_code = self._gen_rvalue(args[0])
                # data ptr
                data_code = base_code + _i32_load(8) if False else None
                # compute addr
                code += self._gen_rvalue(args[0])
                code += _i32_load(8)
                code += idx_code
                code += i64_const(8)
                code += _i64_mul()
                code += bytes([0xA7])
                code += _i32_add()
                # load elem
                if elem_ty is not None and elem_ty.kind == "f64":
                    code += _f64_load(0)
                elif elem_ty is not None and elem_ty.kind in ("i64", "bool"):
                    code += _i64_load(0)
                else:
                    code += _i32_load(0)
                    if elem_ty is not None and elem_ty.kind in ("str", "bytes", "struct", "tuple", "list", "map", "set"):
                        pass
                    else:
                        code += bytes([0xAC])
                if st.call_dest is not None:
                    return self._gen_place_set(st.call_dest, bytes(code), elem_ty)
                return bytes(code)
            if method == "push":
                # Port simplificado del push de AST (con crecimiento).
                recv_ty = self._rv_type(args[0])
                elem_ty = recv_ty.elem if recv_ty is not None else None
                is_float = elem_ty is not None and elem_ty.kind == "f64"
                is_ptr = elem_ty is not None and elem_ty.kind in ("str", "bytes", "struct", "tuple", "list", "map", "set", "func", "closure", "ref")
                code = bytearray()
                # evaluar elemento -> global list_val_*
                code += self._gen_rvalue(args[1])
                if is_float:
                    code += GLOBAL_SET(self.list_val_f64)
                else:
                    if is_ptr:
                        code += bytes([0xAC])
                    code += GLOBAL_SET(self.list_val_i64)
                # list ptr -> tmp_global
                code += self._gen_rvalue(args[0])
                code += GLOBAL_SET(self.tmp_global)
                # if len == cap: grow
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(0)  # len
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(4)  # cap
                code += bytes([0x46])  # i32.eq
                code += bytes([0x04, 0x40])  # if void
                # new data ptr = heap
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_SET(self.list_tmp_global)
                # heap += newcap*8 (cap*2)
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(4)
                code += i32_const(2)
                code += bytes([0x6C])
                code += i32_const(8)
                code += bytes([0x6C])
                code += bytes([0x6A])
                code += GLOBAL_SET(self.heap_global)
                # update cap *= 2
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(4)
                code += i32_const(2)
                code += bytes([0x6C])
                code += _i32_store(4)
                # copy loop
                code += i32_const(0)
                code += GLOBAL_SET(self.list_idx_global)
                code += bytes([0x02, 0x40])  # block
                code += bytes([0x03, 0x40])  # loop
                code += GLOBAL_GET(self.list_idx_global)
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(0)  # old len
                code += bytes([0x4A])  # i32.lt_s
                code += bytes([0x45])  # eqz
                code += bytes([0x0D, 0x01])  # br_if 1
                # dest addr = newdata + idx*8
                code += GLOBAL_GET(self.list_tmp_global)
                code += GLOBAL_GET(self.list_idx_global)
                code += i32_const(8)
                code += bytes([0x6C])
                code += bytes([0x6A])
                # src addr = olddata + idx*8
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(8)
                code += GLOBAL_GET(self.list_idx_global)
                code += i32_const(8)
                code += bytes([0x6C])
                code += bytes([0x6A])
                code += _i64_load(0)
                # store value to dest
                code += _i64_store(0)
                code += GLOBAL_GET(self.list_idx_global)
                code += i32_const(1)
                code += bytes([0x6A])
                code += GLOBAL_SET(self.list_idx_global)
                code += bytes([0x0C, 0x00])
                code += END
                code += END
                # update data ptr
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.list_tmp_global)
                code += _i32_store(8)
                code += bytes([0x0B])  # end if
                # store new element at data + len*8
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(8)  # data ptr
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(0)  # len
                code += bytes([0xAC])
                code += i64_const(8)
                code += _i64_mul()
                code += bytes([0xA7])
                code += bytes([0x6A])
                if is_float:
                    code += GLOBAL_GET(self.list_val_f64)
                    code += _f64_store(0)
                else:
                    code += GLOBAL_GET(self.list_val_i64)
                    code += _i64_store(0)
                # len += 1
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.tmp_global)
                code += _i32_load(0)
                code += i32_const(1)
                code += bytes([0x6A])
                code += _i32_store(0)
                if st.call_dest is not None:
                    # unit: nada
                    pass
                return bytes(code)
            if method == "slice":
                # no implementado completamente; fallback
                self._fail(f"builtin 'list.slice' no soportado en 6.2.7")
        # Métodos/funciones normales (incluye monomorfizados Tipo.m).
        return super()._gen_call(st)

    def _coerce(self, src_ty, wtype):
        # reusar el de aggregates
        return super()._coerce(src_ty, wtype)

    def _i32_load(self, offset):
        return bytes([0x28]) + uleb128(2) + uleb128(offset)

    def _i32_store(self, offset):
        return bytes([0x36]) + uleb128(2) + uleb128(offset)

    def _i64_load(self, offset):
        return bytes([0x29]) + uleb128(3) + uleb128(offset)

    def _i64_store(self, offset):
        return bytes([0x37]) + uleb128(3) + uleb128(offset)

    def _f64_store(self, offset):
        return bytes([0x39]) + uleb128(3) + uleb128(offset)

    def _i32_add(self, a, b):
        return None


# helpers de carga ya definidos en places; reusar nombres
_i32_load = lambda offset: bytes([0x28]) + uleb128(2) + uleb128(offset)
_i64_load = lambda offset: bytes([0x29]) + uleb128(3) + uleb128(offset)
_i64_mul = lambda: bytes([0x7E])
_i64_store = lambda offset: bytes([0x37]) + uleb128(3) + uleb128(offset)
_f64_load = lambda offset: bytes([0x2B]) + uleb128(3) + uleb128(offset)
_f64_store = lambda offset: bytes([0x39]) + uleb128(3) + uleb128(offset)
_i32_store = lambda offset: bytes([0x36]) + uleb128(2) + uleb128(offset)
_i32_add = lambda: bytes([0x6A])
