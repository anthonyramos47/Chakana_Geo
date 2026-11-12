// Page globals the viewer modules share (set in main.js / app_loader.js).
// Only for type checking (npm run typecheck); not served.
interface Window {
  __invalidate?: (frames?: number) => void;
  __renderFrame?: () => void;
  __renderer?: import('three').WebGLRenderer;
  __scene?: import('three').Scene;
  __camera?: import('three').PerspectiveCamera;
  __studio?: any;
  __viewer?: any;
  __toast?: (message: string, kind?: string) => void;
  __up?: string;
  [key: `__${string}`]: any;
}
