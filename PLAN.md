# ARENA FORGE — plan de ejecución (tracker vivo)

Estado: completado el vertical slice + E2E reales. Todo verificado abajo.

- [x] Fase 0: reconocimiento forense (`docs/RECONNAISSANCE.md`)
- [x] Scaffold del subproyecto aislado `arena-forge/`
- [x] Proveniencia upstream (commit, hashes, licencia)
- [x] Motor: `arena_forge.py` (15 comandos) + vendor con patch OpenCode
- [x] Tests deterministas del scheduler (9 passed)
- [x] Skill nativa `.opencode/skills/arena-forge/SKILL.md` + 4 agentes mínimos
- [x] E2E Answer Arena real (4 candidatos, 23 llamadas, campeón a002)
- [x] Fixture Patch Arena + gates + E2E (cand-a PASS/cand-b PASS, juez ciego → cand-a)
- [x] `NO_SHIP` (buggy FAIL), `resume` sin duplicar, outputs inválidos, `apply` con --approve
- [x] Informes MD+HTML con escape en `reports/` (3 runs)
- [x] `ARCHITECTURE.md`, `THREAT_MODEL.md`, 5 ADRs, `CHANGELOG.md`, `README.md`, `LICENSE`
- [x] Benchmark scheduler + gates (`benchmark` → OK)
- [x] Patch adversarial completo (attack/defend v2 + juez v2 90-84)
- [x] README profesional + `demo/` + CHANGELOG 0.2.0
- [x] Publicar en GitHub: rama `master` pusheada a SOCRAMbt/Crew (`7233d0e`)
- [ ] Renombrar el repo a `arena-forge` (requiere web UI o `gh`; ver abajo)
- [ ] `git init` + commit inicial (pendiente: hacerlo al cierre)

Bloqueadores: ninguno. Coste real Answer E2E: 23 llamadas (19 + 4 reintentos).
