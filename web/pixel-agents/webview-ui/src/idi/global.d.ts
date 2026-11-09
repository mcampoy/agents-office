// Global que upstream declara en testHooks.ts (solo para e2e). Se declara acá para el chequeo de tipos de src/idi.
interface Window {
  __pixelAgentsTestHooks?: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}
