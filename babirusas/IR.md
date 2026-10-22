# IR — babirusas

IR de nivel medio (estilo MIR) para borrow checking reutilizable entre lenguajes.

## Unidades

- `Function { name, params: [Param], locals: [Local], blocks: [Block], entry: BlockId }`
- `Param { name, type, mutable }`
- `Local { name, type, mutable }`
- `Block { id, stmts: [Stmt], terminator: Term }`

## Places (lvalues direccionables)

- `Place::Local(name)`
- `Place::Field(base, field)`
- `Place::Index(base, idx)`  (idx es Rvalue/const)
- `Place::Deref(place)`

## Statements

- `StorageLive(place)` / `StorageDead(place)`
- `Assign(place, rvalue)`
- `Borrow { place, kind: Shared|Mut, target }`  // &place / &mut place
- `Call { func, args: [Rvalue], destination: Option<Place>, target: BlockId }`
- `Drop(place)`
- `Nop`

## Rvalues

- `Use(place)` | `Const(value, type)` | `BinOp(op, a, b)` | `UnaryOp(op, a)`
- `Ref(kind, place)` | `Cast(place, type)` | `Aggregate(kind, fields)`

## Terminators

- `Goto(target)` | `SwitchInt(discr, targets)` | `Return` | `Unreachable`

## Tipos

- Primitivos: `i8..i64`, `u8..u64`, `f32`, `f64`, `bool`, `str`, `unit`
- Compuestos: `struct{name, fields}`, `array[T; n]`, `slice[T]`, `ref[T, kind]`

## Reglas de borrow

1. Un place mutable prestado (`&mut`) es exclusivo: ningún otro préstamo activo sobre places solapados.
2. Préstamos compartidos (`&`) permiten múltiples lectores pero ningún mut mientras viva alguno.
3. Un move invalida el place origen; usos posteriores son error.
4. Préstamos parciales: préstamo de campo no bloquea otros campos (salvo struct completo).
5. Lifetimes: cada préstamo vive desde su statement hasta el último uso del target (NLL).
6. Drops implícitos al final de scope (`StorageDead`).

## Convención de traducción

babirusas **no** traduce ASTs. Cada lenguaje (o su compilador) es responsable de
parsear su fuente, construir su AST y bajarlo a BIR (Babirusas IR). babirusas
recibe BIR ya construida y ejecuta únicamente el borrow checking sobre ella.
La frontera es la IR: el productor garantiza que el BIR es válido (tipos,
places, terminators); babirusas asume esa validez y aplica las reglas de borrow.