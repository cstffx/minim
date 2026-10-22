```php
<?php
function push_all(array &$dst, array $src): void {
    foreach ($src as $x) {
        $dst[] = $x;
    }
}

function first_or(array $v, int $d): int {
    if (count($v) === 0) {
        return $d;
    }
    return $v[0];
}
```
