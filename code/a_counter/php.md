```php
<?php
class Counter {
    public int $n = 0;
    public function inc(int $by = 1): int {
        $this->n += $by;
        return $this->n;
    }
}
$c = new Counter();
$c->inc();
$c->inc(3);
echo $c->n . "\n";
```
