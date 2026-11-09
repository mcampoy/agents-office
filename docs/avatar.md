# Avatar del responsable y variantes de personajes

Las hojas de personajes se generan en build con `web/pixel-agents/idi/sprites.mjs` (Node + pngjs, que ya es dependencia del build). En uso diario no hace falta Node.

```
cd web/pixel-agents
npm run sprites        # solo los sprites (npm run build los regenera siempre)
```

Salida en `web/pixel-agents/.build/` (no se versiona):

| Archivo | Qué es |
|---|---|
| `assets/characters/char_0..5.png` | Los seis sprites base de Pixel Agents, sin cambios |
| `assets/characters/char_6..23.png` | Variantes de ropa: tres por sprite base |
| `assets/characters/char_24.png` | Avatar del responsable |
| `assets/personajes.json` | Índice de cada hoja, cuál es el avatar y cuáles se asignan a agentes |
| `vista-avatar.png` | `char_4` y el avatar, ampliados ×6, para revisar |
| `vista-variantes.png` | Todas las hojas ampliadas ×2 |

Formato de cada hoja (el de upstream): 112×96, cuadros de 16×32, 7 por fila (caminar ×3, tipear ×2, leer ×2) y 3 filas (abajo, arriba, derecha). La izquierda la espeja el renderer.

## Variantes: recolor por máscara de paleta (decisión 7)

- `ROPA` lista, por sprite base, los colores exactos de la ropa, leídos del cuadro 0.
- Cada variante reemplaza solo esos colores por una rampa del tono elegido. Los colores se ordenan por luminancia y van de 24 % a 68 % de luz, así se conserva el sombreado.
- Piel, pelo, ojos y contorno no se tocan. Esa es la diferencia con el `hueShift` de upstream, que también cambiaba la piel.
- En `char_0` la campera y el pantalón comparten paleta, así que cambia el conjunto entero.

## Avatar: capas sobre `char_4`

Se eligió `char_4` porque ya tiene pelo castaño en punta, remera blanca y pantalón azul marino, igual que la imagen de referencia de la persona (que vive en el perfil del equipo, no en este repo). El avatar actual reproduce esos rasgos; para otra persona hay que ajustar las capas de abajo.

| Capa | Cómo se aplica |
|---|---|
| Pelo castaño oscuro | Reemplazo exacto de los seis colores de pelo de `char_4` por versiones más oscuras |
| Zapatillas blancas | Reemplazo de los tres grises de calzado, solo en las filas 24 a 31 del cuadro (el mismo gris aparece en el brillo de los ojos) |
| Anteojos (mirando abajo) | Se busca la fila de los ojos: la primera con negro en las columnas 5 y 10. En esa fila se pintan de marco oscuro las columnas 4, 7, 8 y 11 (bordes y puente) y los costados 3 y 12. La frente queda con piel para que el marco no se funda con el pelo |
| Anteojos (de perfil) | Se busca el ojo: el primer par negro horizontal en la mitad derecha de la cabeza. Se pinta el borde superior, el borde de atrás y la patilla hacia la oreja |
| Barba | Mirando abajo: la piel de la fila `ojos + 3` (mandíbula) y las patillas en `ojos + 2`. De perfil: las filas `ojo + 3` y `ojo + 4`, más la patilla |
| Infinito en la remera | Un ∞ de 5×3 en azul y turquesa, dos filas debajo del cuello. Solo en los cuadros que miran abajo y no leen (en lectura, la hoja tapa el pecho) |

Los cuadros de lectura de upstream ya traen anteojos de lectura para todos los personajes. En esos cuadros el script detecta que ya hay marco y no agrega otro.

**Para retocarlo:** cambiar los colores de `AV` o las filas y columnas en `avatar()`, correr `npm run sprites` y mirar `vista-avatar.png`. Para ver un cuadro suelto muy ampliado:

```
node idi/zoom.mjs .build/assets/characters/char_24.png salida.png 0,0 3,0 0,2
```

Cada par es `cuadro,fila`: fila 0 es abajo, 1 arriba y 2 derecha.

## Asignación a agentes

- `sprites.json` del perfil fija el sprite de un agente por nombre o patrón (`lente-*`), con el índice de `personajes.json`.
- Sin regla, el sprite se elige de forma determinística a partir del nombre (hash FNV-1a) entre los asignables: todos menos el avatar y `char_4` original, que se le parece demasiado.
- Si dos tipos presentes caen en el mismo sprite, el segundo toma el siguiente libre.
- Las instancias de un mismo tipo comparten sprite. Se distinguen por la etiqueta (`#n` y la `description`).

## Licencias

- Los sprites base son de Pixel Agents (MIT, © 2026 Pablo De Lucca), basados en el pack MetroCity de JIK-A-4 (CC0).
- Las variantes y el avatar son derivados de esos sprites: se distribuyen con el aviso MIT y con crédito a JIK-A-4, aunque CC0 no lo exige.
