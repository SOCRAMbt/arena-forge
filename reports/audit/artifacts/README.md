# Evidencia verificable del E2E Patch Arena

Estos artefactos permiten a un tercero **verificar la cadena de decision** sin
ejecutar el E2E:

| Fichero | Que demuestra |
|---|---|
| `gates.json` | El veredicto por candidato: estado, `suite_sha`, `candidate_manifest_sha` y `diff_sha` |
| `decision.json` | La decision persistida: `decision_id` (ligado al contenido), `winner_id`, `diff_sha` |
| `isolation.json` | La prueba de aislamiento de los workspaces |
| `ledger.jsonl` | El historial append-only con cadena de hashes |
| `run-20261019-195822-s21.patch` | El parche round-trip exportado (parche **Git real**) |
| `SHA256SUMS.txt` | SHA-256 de cada artefacto |

## Comprobacion manual

```bat
certutil -hashfile reports\audit\artifacts\run-20261019-195822-s21.patch SHA256
```

El resultado **debe** coincidir con:

- `diff_sha` del gate del ganador en `gates.json`, y
- `diff_sha` en `decision.json`.

Si los tres coinciden, el parche entregado es exactamente el diff evaluado.

Ademas, el parche aplica sobre el baseline con:

```bat
git -c core.autocrlf=false -c core.eol=lf apply --check ^
    reports\audit\artifacts\run-20261019-195822-s21.patch
```

> `core.autocrlf=false` es **obligatorio**: con el valor de sistema de Windows
> (`true`), `git apply` reescribe LF->CRLF y el arbol resultante deja de
> coincidir byte a byte con el candidato evaluado.
