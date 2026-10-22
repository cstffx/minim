```php
<?php
function countWords(string $path): array
{
    $c = [];
    $fh = fopen($path, 'r');
    if ($fh === false) {
        throw new RuntimeException("cannot open $path");
    }
    while (($line = fgets($fh)) !== false) {
        foreach (preg_split('/\s+/', trim($line)) as $w) {
            if ($w === '') {
                continue;
            }
            $key = strtolower(trim($w, ".,;:!?"));
            $c[$key] = ($c[$key] ?? 0) + 1;
        }
    }
    fclose($fh);
    return $c;
}

$path = $argv[1] ?? 'in.txt';
try {
    $c = countWords($path);
} catch (Throwable $e) {
    fwrite(STDERR, "error: {$e->getMessage()}\n");
    return;
}
arsort($c);
$i = 0;
foreach ($c as $w => $k) {
    if ($i++ >= 10) {
        break;
    }
    printf("%6d %s\n", $k, $w);
}
```
