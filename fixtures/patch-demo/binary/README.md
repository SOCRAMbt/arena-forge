# Artefacto binario de prueba

`sample.bin` (SHA-256 se verifica en el test) contiene:

- bytes `0x00`-`0xFF` repetidos (cubre NUL, byte de control y byte alto),
- una cola con `0xFF 0xFE` (**no es UTF-8 valido**: obliga a clasificar el
  fichero como binario aunque NO tenga NUL al principio),
- una terminacion ASCII.

Sirve para dos cosas:

1. **Fixture persistente**: el round-trip binario se puede reproducir desde un
   checkout limpio (el test `BinaryPatchTest::test_persisted_binary_fixture_roundtrip`
   lo usa).
2. **Evidencia de la auditoria**: la clasificacion binaria y el round-trip
   byte-exacto dejan de depender de ficheros generados en tiempo de ejecucion.
