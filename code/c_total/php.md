```php
<?php
function total(array $lines): int {
    $t = 0;
    foreach ($lines as $s) {
        $n = filter_var(trim($s), FILTER_VALIDATE_INT);
        if ($n === false) {
            continue;
        }
        if ($n % 2 === 0) {
            $t += $n;
        }
    }
    return $t;
}
```
