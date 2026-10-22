from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, NIL
from tools.nodes import *
from .util import _unsupported
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static

class MatchMixin:
        def _tuple_layout(self, ty):
            # ty: ("tuple", (t1, t2, ...))
            items = ty[1] if (isinstance(ty, tuple) and ty[0] == "tuple") else ()
            if not isinstance(items, (tuple, list)):
                items = (items,)
            fields = []
            off = 0
            for it in items:
                wt = self._wasm_type(it)
                fields.append((wt, off, it))
                off += 8
            if off == 0:
                off = 8
            return off, fields

        def _ensure_map_get_helper(self, is_float_val):
            if is_float_val in self._map_get_helpers:
                return self._map_get_helpers[is_float_val]
            # type: (i64, i64) -> i64
            typeidx = self.enc.add_type([WasmEncoder.I32, WasmEncoder.I64], [WasmEncoder.I64])
            code = bytearray()
            # params: 0 = map_ptr (i32), 1 = key (i64)
            code += local_get(0)
            code += GLOBAL_SET(self.tmp_global)  # map ptr
            # n = map.len
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += GLOBAL_SET(self.list_tmp_global)  # n (i32)
            # found = 0
            code += i64_const(0)
            code += GLOBAL_SET(self.match_scrut_i64)
            # i = 0
            code += i32_const(0)
            code += GLOBAL_SET(self.list_idx_global)
            code += bytes([0x03, 0x40])  # loop
            # if i >= n: break loop (return found)
            code += GLOBAL_GET(self.list_idx_global)
            code += GLOBAL_GET(self.list_tmp_global)
            code += bytes([0x48])  # i32.lt_s
            code += bytes([0x45])  # i32.eqz
            code += bytes([0x04, 0x40])  # if i>=n
            code += GLOBAL_GET(self.match_scrut_i64)
            code += RETURN
            code += bytes([0x0B])
            # load key at entry
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)  # data ptr
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(16)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)  # key (i64)
            # compare with param key (local 1)
            code += local_get(1)
            code += I64_EQ
            code += bytes([0x04, 0x40])  # if match
            # load value at entry+8
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(16)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += i32_const(8)
            code += bytes([0x6A])
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += GLOBAL_SET(self.match_scrut_i64)
            # i = n to exit loop
            code += GLOBAL_GET(self.list_tmp_global)
            code += GLOBAL_SET(self.list_idx_global)
            code += bytes([0x0B])  # end if
            # i++
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(1)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.list_idx_global)
            code += bytes([0x0C, 0x00])  # br 0
            code += bytes([0x0B])  # end loop
            code += GLOBAL_GET(self.match_scrut_i64)
            code += RETURN
            idx = self.enc.add_function(typeidx, [], bytes(code))
            name = f"__map_get_{int(is_float_val)}"
            self.func_index[name] = idx
            self._map_get_helpers[is_float_val] = (name, idx)
            return name, idx

        def _gen_bind_pattern(self, pat, scrut_ty, offset, code, qname):
            # Assumes current struct pointer in match_addr_i64.
            if pat.kind == "name" and pat.value:
                vi = self.locals_map[qname].get(pat.value)
                if vi is None:
                    vi = len(self.locals_map[qname])
                    self.locals_map[qname][pat.value] = vi
                if scrut_ty == FLOAT:
                    code += GLOBAL_GET(self.match_addr_i64)
                    code += bytes([0xA7])
                    code += bytes([0x2B])  # f64.load
                    code += _uleb128_static(3)
                    code += _uleb128_static(offset)
                elif isinstance(scrut_ty, tuple) and scrut_ty[0] in ("named", "list", "map", "set", "tuple", "borrow") or scrut_ty == STR:
                    code += GLOBAL_GET(self.match_addr_i64)
                    code += bytes([0xA7])
                    code += bytes([0x28])  # i32.load
                    code += _uleb128_static(2)
                    code += _uleb128_static(offset)
                    code += bytes([0xAC])  # extend
                else:
                    code += GLOBAL_GET(self.match_addr_i64)
                    code += bytes([0xA7])
                    code += bytes([0x29])  # i64.load
                    code += _uleb128_static(3)
                    code += _uleb128_static(offset)
                code += local_set(vi)
                return
            if isinstance(scrut_ty, tuple) and scrut_ty[0] == "tuple" and pat.kind == "tuple":
                size, fields = self._tuple_layout(scrut_ty)
                bound = set()
                for p in (pat.patterns or []):
                    idx = None
                    if p.kind == "named_field":
                        # tuples have no names; treat positional
                        pass
                    if idx is None:
                        for j in range(len(fields)):
                            if j not in bound:
                                idx = j
                                break
                    if idx is None or idx >= len(fields):
                        continue
                    bound.add(idx)
                    wt, foff, fty = fields[idx]
                    sub = p.sub if p.kind == "named_field" else p
                    if fty is not None and isinstance(fty, tuple) and fty[0] in ("tuple", "named"):
                        # save parent addr
                        code += GLOBAL_GET(self.match_addr_i64)
                        code += bytes([0xA7])
                        code += GLOBAL_SET(self.tmp_global)  # tmp_global i32 (parent addr)
                        # load field ptr
                        code += GLOBAL_GET(self.match_addr_i64)
                        code += bytes([0xA7])
                        if wt == WasmEncoder.I32:
                            code += bytes([0x28])
                            code += _uleb128_static(2)
                        else:
                            code += bytes([0x29])
                            code += _uleb128_static(3)
                        code += _uleb128_static(offset + foff)
                        if wt != WasmEncoder.I32:
                            code += bytes([0xA7])
                        code += bytes([0xAC])  # extend to i64
                        code += GLOBAL_SET(self.match_addr_i64)
                        self._gen_bind_pattern(sub, fty, 0, code, qname)
                        # restore parent addr
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0xAC])
                        code += GLOBAL_SET(self.match_addr_i64)
                    else:
                        self._gen_bind_pattern(sub, fty, offset + foff, code, qname)
                return
            # variant nested
            if isinstance(scrut_ty, tuple) and scrut_ty[0] == "named" and scrut_ty[1] in self.sum_types and pat.kind == "variant":
                sum_name = scrut_ty[1]
                vfs = self.variant_fields[sum_name].get(pat.name, [])
                field_index = {f[0]: i for i, f in enumerate(vfs)}
                bound = set()
                for p in (pat.patterns or []):
                    idx = None
                    if p.kind == "named_field":
                        idx = field_index.get(p.field_name)
                    elif p.kind in ("name",):
                        for j in range(len(vfs)):
                            if j not in bound:
                                idx = j
                                break
                    if idx is None or idx >= len(vfs):
                        continue
                    bound.add(idx)
                    fname, fwtype, off, fty, fdefault = vfs[idx]
                    sub = p.sub if p.kind == "named_field" else p
                    if fty is not None and isinstance(fty, tuple) and fty[0] in ("tuple", "named") and isinstance(fty, tuple) and fty[0] == "named" and fty[1] in self.sum_types or (isinstance(fty, tuple) and fty[0] == "tuple"):
                        # save parent addr
                        code += GLOBAL_GET(self.match_addr_i64)
                        code += bytes([0xA7])
                        code += GLOBAL_SET(self.tmp_global)
                        # load field ptr (variant fields are at fixed offsets)
                        code += GLOBAL_GET(self.match_addr_i64)
                        code += bytes([0xA7])
                        if fwtype == WasmEncoder.I32:
                            code += bytes([0x28])
                            code += _uleb128_static(2)
                        elif fwtype == WasmEncoder.F64:
                            code += bytes([0x2B])
                            code += _uleb128_static(3)
                        else:
                            code += bytes([0x29])
                            code += _uleb128_static(3)
                        code += _uleb128_static(off)
                        if fwtype != WasmEncoder.I32:
                            code += bytes([0xA7])
                        code += bytes([0xAC])
                        code += GLOBAL_SET(self.match_addr_i64)
                        self._gen_bind_pattern(sub, fty, 0, code, qname)
                        # restore
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0xAC])
                        code += GLOBAL_SET(self.match_addr_i64)
                    else:
                        self._gen_bind_pattern(sub, fty, off, code, qname)
                return

        def _gen_match_core(self, scrut_expr, arms, code, qname, fn, want_value=True):
            scrut_ty = self._tc_type(scrut_expr, qname)
            is_float_scrut = (scrut_ty == FLOAT)
            self._gen_expr(scrut_expr, code, qname)
            if is_float_scrut:
                code += GLOBAL_SET(self.match_scrut_f64)
            else:
                if isinstance(scrut_ty, tuple) and scrut_ty[0] in ("named", "list", "map", "set", "tuple", "borrow") or scrut_ty == STR:
                    code += bytes([0xAC])
                code += GLOBAL_SET(self.match_scrut_i64)
            # block type
            try:
                # typecheck as MatchStmt-like using a temporary? Use tc.stmt with a MatchStmt node
                import tools.nodes as _nodes
                ms = _nodes.MatchStmt(scrut_expr, arms)
                scope = self.scope_map.get(qname, self.tc.module_scope)
                old = getattr(self.tc, "cur_type", None)
                if "." in (qname or ""):
                    self.tc.cur_type = qname.split(".")[0]
                match_ty = self.tc.stmt(ms, scope)
                self.tc.cur_type = old
            except Exception:
                match_ty = None
            if want_value:
                wtype = self._wasm_type(match_ty) if match_ty not in (None, NIL) else None
            else:
                wtype = None
            code += BLOCK(wtype if wtype is not None else BLK_VOID)
            sum_name = None
            if isinstance(scrut_ty, tuple) and scrut_ty[0] == "named":
                sum_name = scrut_ty[1]
            for arm in (arms or []):
                if getattr(arm, "is_else", False):
                    continue
                code += BLOCK(BLK_VOID)
                is_variant_arm = (sum_name is not None and (
                    arm.pattern.kind == "variant" or
                    (arm.pattern.kind == "name" and arm.pattern.value in self.variant_index.get(sum_name, {}))))
                # tag check for variants
                if is_variant_arm:
                    code += GLOBAL_GET(self.match_scrut_i64)
                    code += bytes([0xA7])
                    code += bytes([0x28])
                    code += _uleb128_static(2)
                    code += _uleb128_static(0)
                    vname = arm.pattern.name if arm.pattern.kind == "variant" else arm.pattern.value
                    tag = self.variant_index[sum_name].get(vname, -1)
                    code += i32_const(tag)
                    code += bytes([0x46])
                    code += bytes([0x45])
                    code += bytes([0x0D, 0x00])
                # literal pattern check
                if (not is_variant_arm) and arm.pattern.kind == "literal":
                    val = arm.pattern.value
                    if scrut_ty == INT or (isinstance(scrut_ty, tuple) and scrut_ty == ("p", "int")):
                        if isinstance(val, str):
                            try: val = int(val)
                            except: pass
                    elif scrut_ty == FLOAT:
                        if isinstance(val, str):
                            try: val = float(val)
                            except: pass
                    elif scrut_ty == BOOL or (isinstance(scrut_ty, tuple) and scrut_ty == ("p", "bool")):
                        if isinstance(val, str):
                            val = (val == "true")
                    if scrut_ty == FLOAT:
                        code += GLOBAL_GET(self.match_scrut_f64)
                        code += f64_const(float(val) if not isinstance(val, (int, float, bool)) else (1.0 if val is True else 0.0 if val is False else float(val)))
                        code += F64_EQ
                    elif isinstance(val, bool):
                        code += GLOBAL_GET(self.match_scrut_i64)
                        code += i64_const(1 if val else 0)
                        code += I64_EQ
                    elif isinstance(val, int):
                        code += GLOBAL_GET(self.match_scrut_i64)
                        code += i64_const(val)
                        code += I64_EQ
                    elif isinstance(val, str):
                        code += GLOBAL_GET(self.match_scrut_i64)
                        code += bytes([0xA7])
                        ptr = getattr(self, "str_value_offsets", {}).get(val, 0)
                        code += i32_const(ptr)
                        code += bytes([0x46])  # i32.eq
                    code += bytes([0x45])  # i32.eqz
                    code += bytes([0x0D, 0x00])
                # init match_addr for nested binding
                code += GLOBAL_GET(self.match_scrut_i64)
                code += GLOBAL_SET(self.match_addr_i64)

                # tuple pattern binding (recursive)
                if isinstance(scrut_ty, tuple) and scrut_ty[0] == "tuple" and arm.pattern.kind == "tuple":
                    self._gen_bind_pattern(arm.pattern, scrut_ty, 0, code, qname)

                # bind fields (variant) (recursive)
                if sum_name is not None and arm.pattern.kind == "variant":
                    self._gen_bind_pattern(arm.pattern, ("named", sum_name, ()), 0, code, qname)
                # bind simple name pattern (catch-all binding)
                if arm.pattern.kind == "name" and not is_variant_arm:
                    vi = self.locals_map[qname].get(arm.pattern.value)
                    if vi is None:
                        vi = len(self.locals_map[qname])
                        self.locals_map[qname][arm.pattern.value] = vi
                    if scrut_ty == FLOAT:
                        code += GLOBAL_GET(self.match_scrut_f64)
                    elif isinstance(scrut_ty, tuple) and scrut_ty[0] in ("named", "list", "map", "set", "tuple", "borrow") or scrut_ty == STR:
                        code += GLOBAL_GET(self.match_scrut_i64)
                        code += bytes([0xA7])
                    else:
                        code += GLOBAL_GET(self.match_scrut_i64)
                    code += local_set(vi)
                # guard
                if arm.guard is not None:
                    self._gen_expr(arm.guard, code, qname)
                    code += i64_const(0)
                    code += I64_EQ
                    code += bytes([0x0D, 0x00])
                # body
                if isinstance(arm.body, Suite):
                    self._gen_suite(arm.body, code, qname, fn, want_value)
                elif arm.body is not None:
                    self._gen_expr(arm.body, code, qname)
                    if not want_value:
                        ty = self._tc_type(arm.body, qname)
                        if ty != NIL:
                            code += DROP
                code += bytes([0x0C, 0x01])
                code += bytes([0x0B])
            # else arms
            for arm in (arms or []):
                if not getattr(arm, "is_else", False):
                    continue
                if isinstance(arm.body, Suite):
                    self._gen_suite(arm.body, code, qname, fn, want_value)
                elif arm.body is not None:
                    self._gen_expr(arm.body, code, qname)
                    if not want_value:
                        ty = self._tc_type(arm.body, qname)
                        if ty != NIL:
                            code += DROP
                code += bytes([0x0C, 0x00])
            # default
            if want_value:
                if wtype == WasmEncoder.F64:
                    code += f64_const(0.0)
                elif wtype == WasmEncoder.I32:
                    code += i32_const(0)
                else:
                    code += i64_const(0)
            code += bytes([0x0B])

        def _collect_pattern_binding_types(self, pat, scrut_ty, result):
            if pat is None:
                return
            if pat.kind == "name":
                if pat.value:
                    result[pat.value] = scrut_ty
                return
            if pat.kind == "variant":
                if isinstance(scrut_ty, tuple) and scrut_ty[0] == "named":
                    td = self.tc.type_defs.get(scrut_ty[1])
                    targs = scrut_ty[2] if len(scrut_ty) > 2 else ()
                    variant = None
                    if td is not None:
                        for m in td.members:
                            if m.kind == "variant" and m.node.name == pat.name:
                                variant = m.node
                                break
                    if variant is not None:
                        vfs = variant.fields if variant.fields else [mm.node for mm in getattr(variant, "members", []) if isinstance(mm.node, Field)]
                        for i, p in enumerate(pat.patterns or []):
                            ft = UNKNOWN
                            if i < len(vfs):
                                f = vfs[i]
                                if f.type_ is not None:
                                    ft = self.tc._atype(f.type_)
                                    ft = self.tc._sub(ft, td.tparams, targs)
                            self._collect_pattern_binding_types(p, ft, result)
                        return
                for p in (pat.patterns or []):
                    self._collect_pattern_binding_types(p, scrut_ty, result)
                return
            if pat.kind == "tuple":
                if isinstance(scrut_ty, tuple) and scrut_ty[0] == "tuple":
                    items = scrut_ty[1] if isinstance(scrut_ty[1], (tuple, list)) else ()
                    for p, et in zip(pat.patterns or [], items):
                        self._collect_pattern_binding_types(p, et, result)
                else:
                    for p in (pat.patterns or []):
                        self._collect_pattern_binding_types(p, scrut_ty, result)
                return
            if pat.kind == "named_field":
                ft = scrut_ty
                if isinstance(scrut_ty, tuple) and scrut_ty[0] == "named":
                    td = self.tc.type_defs.get(scrut_ty[1])
                    targs = scrut_ty[2] if len(scrut_ty) > 2 else ()
                    if td is not None:
                        field = None
                        for m in td.members:
                            if m.kind == "field" and m.node.name == pat.field_name:
                                field = m.node
                                break
                        if field is not None and field.type_ is not None:
                            ft = self.tc._atype(field.type_)
                            ft = self.tc._sub(ft, td.tparams, targs)
                if pat.sub is not None:
                    self._collect_pattern_binding_types(pat.sub, ft, result)
                return

        def _match_bound_types(self, st, qname):
            result = {}
            scrut_ty = self._tc_type(st.expr, qname)
            for arm in (st.arms or []):
                if getattr(arm, "is_else", False):
                    continue
                pat = arm.pattern
                if scrut_ty is None:
                    self._collect_pattern_binding_types(pat, None, result)
                    continue
                if isinstance(scrut_ty, tuple) and scrut_ty[0] == "named":
                    td = self.tc.type_defs.get(scrut_ty[1])
                    # variant pattern
                    if pat.kind == "variant" and td is not None:
                        variant = None
                        for m in td.members:
                            if m.kind == "variant" and m.node.name == pat.name:
                                variant = m.node
                                break
                        if variant is not None:
                            targs = scrut_ty[2] if len(scrut_ty) > 2 else ()
                            vfs = variant.fields if variant.fields else [mm.node for mm in getattr(variant, "members", []) if isinstance(mm.node, Field)]
                            field_index = {f.name if hasattr(f,'name') else (f[0] if isinstance(f,tuple) else None): i for i, f in enumerate(vfs)}
                            # field name may be f.name for Field node; vfs elements are Field nodes here
                            field_index = {}
                            for i, f in enumerate(vfs):
                                fnm = getattr(f, "name", None)
                                if fnm is None and isinstance(f, tuple):
                                    fnm = f[0]
                                field_index[fnm] = i
                            bound = set()
                            for p in (pat.patterns or []):
                                idx = None
                                if p.kind == "named_field":
                                    idx = field_index.get(p.field_name)
                                elif p.kind in ("name",):
                                    for j in range(len(vfs)):
                                        if j not in bound:
                                            idx = j
                                            break
                                if idx is None or idx >= len(vfs):
                                    continue
                                bound.add(idx)
                                f = vfs[idx]
                                ft = UNKNOWN
                                if getattr(f, "type_", None) is not None:
                                    ft = self.tc._atype(f.type_)
                                    ft = self.tc._sub(ft, td.tparams, targs)
                                sub = p.sub if p.kind == "named_field" else p
                                self._collect_pattern_binding_types(sub, ft, result)
                            continue
                    # name binding whole scrutinee (but not a variant tag used as pattern)
                    if pat.kind == "name":
                        if isinstance(scrut_ty, tuple) and scrut_ty[0] == "named" and scrut_ty[1] in self.variant_index and pat.value in self.variant_index.get(scrut_ty[1], {}):
                            continue
                        result[pat.value] = scrut_ty
                        continue
                    self._collect_pattern_binding_types(pat, scrut_ty, result)
                else:
                    self._collect_pattern_binding_types(pat, scrut_ty, result)
            return result
