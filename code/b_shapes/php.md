```php
<?php
class Circle {
    public function __construct(public float $r) {}
}
class Rect {
    public function __construct(public float $w, public float $h) {}
}

function area(object $s): float {
    if ($s instanceof Circle) {
        return 3.14159 * $s->r * $s->r;
    }
    if ($s instanceof Rect) {
        return $s->w * $s->h;
    }
    throw new InvalidArgumentException('unknown shape');
}
```
