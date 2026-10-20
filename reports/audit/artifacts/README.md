# Evidencia verificable del E2E Patch Arena

Estos artefactos permiten a un tercero **verificar la cadena de decision** sin
ejecutar el E2E:

| Fichero | Que demuestra |
|---|---|
| `gates.json` | El veredicto por candidato: estado, `suite_sha`, `candidate_manifest_sha` y `diff_sha` |
| `decision.json` | La decision persistida: `decision_id` (ligado al contenido), `winner_id`, `diff_sha` |
| `isolation.json` | La prueba de aislamiento de los workspaces |
| `ledger.jsonl` | El historial append-only con cadena de hashes |
| `run-20261019-210128-s31.patch` | El parche round-trip exportado (parche **Git real**) |
| `SHA256SUMS.txt` | SHA-256 de cada artefacto |

## Comprobacion manual

```bat
certutil -hashfile reports\audit\artifacts\run-20261019-210128-s31.patch SHA256
```

El resultado **debe** coincidir con:

- `diff_sha` del gate del ganador en `gates.json`, y
- `diff_sha` en `decision.json`.

Si los tres coinciden, el parche entregado es exactamente el diff evaluado.

Valor verificado en la ejecucion:

```
sha256(parche exportado) = c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f
diff_sha del gate         = c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f
diff_sha de decision.json = c68f82cde82f99a62b22d055be908c13fa957222114deecd589c88a7f718f59f
```

## Aplicacion sobre el baseline

El parche usa rutas **relativas al directorio del baseline**, asi que se
comprueba desde el repo destino indicando ese directorio:

```bat
git -c core.autocrlf=false -c core.eol=lf apply --check ^
    --directory=fixtures/patch-demo/baseline_buggy ^
    reports\audit\artifacts\run-20261019-210128-s31.patch
```

> `core.autocrlf=false` es **obligatorio**: con el valor de sistema de Windows
> (`true`), `git apply` reescribe LF->CRLF y el arbol resultante deja de
> coincidir byte a byte con el candidato evaluado.

## Sobre los finales de linea

Los artefactos de texto se escriben **siempre con LF** (`newline=""` en los
escritores de `forge/util.py`) y el manifiesto `SHA256SUMS.txt` se calcula
sobre el contenido **normalizado a LF**, que es exactamente lo que git
versiona. Por eso el manifiesto es valido tanto en el working tree de Windows
como en un checkout limpio de Linux, y en cualquier plataforma.
