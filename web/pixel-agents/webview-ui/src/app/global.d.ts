// Global that upstream declares in testHooks.ts (e2e only). Declared here for the type check of src/app.
interface Window {
  __pixelAgentsTestHooks?: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}
