# BBIR — Binary Babirusas IR

Formato binario de intercambio de BIR entre productores (compiladores) y babirusas.

## Convenciones

- Endianness: **little-endian**.
- Enteros: LEB128 sin signo (`uleb128`) para índices/longitudes; `i64`/`i32` little-endian para valores.
- Strings: `uleb128 len` + bytes UTF-8.
- Todos los enums son `u8`.
- Magic: `BBIR` (4 bytes) + versión `u32` (actual: 1).

## Estructura del módulo

```
magic:      [4] "BBIR"
version:    u32
n_funcs:    uleb128
functions:  [Function] * n_funcs
```

## Function

```
name:       string
n_params:   uleb128
params:     [Param] * n_params
n_locals:   uleb128
locals:     [Local] * n_locals
n_blocks:   uleb128
blocks:     [Block] * n_blocks
entry:      uleb128   (BlockId)
```

## Param / Local

```
name:       string
type:       Type
mutable:    u8 (0/1)
```

## Block

```
id:         uleb128
n_stmts:    uleb128
stmts:      [Stmt] * n_stmts
terminator: Term
```

## Type (tag u8 + payload)

- `0x00` unit
- `0x01` bool
- `0x02` i8 `0x03` i16 `0x04` i32 `0x05` i64
- `0x06` u8 `0x07` u16 `0x08` u32 `0x09` u64
- `0x0A` f32 `0x0B` f64
- `0x0C` str
- `0x10` struct: `name: string`, `n_fields: uleb128`, `[field: string, type: Type]`
- `0x11` array: `elem: Type`, `len: uleb128`
- `0x12` slice: `elem: Type`
- `0x13` ref: `kind: u8 (0=shared,1=mut)`, `pointee: Type`

## Place (tag u8 + payload)

- `0x00` local: `name: string`
- `0x01` field: `base: Place`, `field: string`
- `0x02` index: `base: Place`, `idx: Rvalue`  (Rvalue serializado inline)
- `0x03` deref: `base: Place`

## Rvalue (tag u8 + payload)

- `0x00` use: `place: Place`
- `0x01` const: `type: Type`, `value` (i64/f64/bool/str según type)
- `0x02` binop: `op: u8`, `a: Rvalue`, `b: Rvalue`
- `0x03` unaryop: `op: u8`, `a: Rvalue`
- `0x04` ref: `kind: u8`, `place: Place`
- `0x05` cast: `place: Place`, `type: Type`
- `0x06` aggregate: `kind: u8`, `n: uleb128`, `[Rvalue]`

## Stmt (tag u8 + payload)

- `0x00` StorageLive: `place: Place`
- `0x01` StorageDead: `place: Place`
- `0x02` Assign: `place: Place`, `rvalue: Rvalue`
- `0x03` Borrow: `kind: u8`, `place: Place`, `target: string` (local name)
- `0x04` Call: `func: string`, `n_args: uleb128`, `[Rvalue]`, `dest: Option<Place>` (0/1 + Place), `target: uleb128`
- `0x05` Drop: `place: Place`
- `0x06` Nop

## Term (tag u8 + payload)

- `0x00` Goto: `target: uleb128`
- `0x01` SwitchInt: `discr: Rvalue`, `n: uleb128`, `[ (value: i64, target: uleb128) ]`, `otherwise: uleb128`
- `0x02` Return
- `0x03` Unreachable

## Notas

- `BlockId` es índice en `Function.blocks` (uleb128).
- `Option<Place>` se codifica como `u8` (0 = None, 1 = Some) seguido del Place.
- Los enums de `op` (binop/unaryop) se definen en una tabla aparte (docs/OPS.md) para mantener estabilidad.
- Versión se incrementa solo con cambios incompatibles.
